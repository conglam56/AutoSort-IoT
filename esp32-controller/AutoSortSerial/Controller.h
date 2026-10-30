#pragma once
#include <stdint.h>
#include <string.h>

namespace autosort {

struct Config {
  uint32_t irToCameraMs = 300;
  uint32_t settleMs = 150;
  uint32_t aiTimeoutMs = 30000;
  uint32_t heartbeatMs = 5000;
  uint32_t debounceMs = 20;
  uint32_t cameraToGate1Ms = 1200;
  uint32_t cameraToGate2Ms = 2500;
  uint32_t gateHoldMs = 400;
  uint32_t exitClearMs = 500;
};

enum class State { WAIT_BRIDGE, RUNNING, TO_CAMERA, SETTLING, WAIT_AI, DISPATCH, FAULT, IDLE, PAUSED };
enum class Label { GREEN, RIPE, REJECT };

// Hardware-independent state machine; the sketch applies outputs before emitting a trigger.
// Exactly one fruit may occupy the conveyor. There is deliberately no overlapping queue.
class Controller {
 public:
  explicit Controller(Config config = Config()) : config_(config) {}

  void begin(uint32_t now, bool irBlocked) {
    state_ = State::WAIT_BRIDGE;
    entered_ = lastContact_ = rawChanged_ = now;
    rawBlocked_ = stableBlocked_ = irBlocked;
    irArmed_ = !irBlocked;
  }

  void stop(const char* reason) {
    state_ = State::FAULT;
    fault_ = reason;
    motor_ = false;
    gate1_ = gate2_ = 0;
    trigger_ = false;
    ackPending_ = false;
  }

  void command(const char* line, uint32_t now) {
    if (strcmp(line, "BRIDGE:STOP") == 0) { stop("BRIDGE_STOP"); return; }
    if (state_ == State::FAULT) return;  // Reset and inspect; READY cannot clear a fault.
    if (strcmp(line, "BRIDGE:CONNECT") == 0 && state_ == State::WAIT_BRIDGE) {
      state_ = State::IDLE; lastContact_ = now; webMode_=true; return;
    }
    if (strncmp(line, "CONTROL:", 8) == 0) { control(line + 8, now); return; }
    if (strncmp(line, "RESULT:", 7) == 0) {
      const char* cursor = line + 7;
      if (strlen(cursor) < 35 || strncmp(cursor,session_,32)!=0 || cursor[32]!=':') return;
      cursor += 33;
      uint32_t counter = 0;
      unsigned digits = 0;
      while (*cursor >= '0' && *cursor <= '9') {
        const uint32_t digit = static_cast<uint32_t>(*cursor++ - '0');
        if (++digits > 10 || counter > (UINT32_MAX-digit)/10) return;
        counter = counter*10+digit;
      }
      if (!digits || *cursor++ != ':' || counter != counter_) return;
      acceptLabel(cursor,now); return;
    }
    if (strncmp(line, "BRIDGE:READY:", 13) == 0) {
      if (state_ != State::WAIT_BRIDGE) { stop("UNEXPECTED_READY"); return; }
      const char* id = line + 13;
      if (strlen(id) != 32) { stop("INVALID_SESSION"); return; }
      for (int i = 0; i < 32; ++i) {
        if (!((id[i] >= '0' && id[i] <= '9') || (id[i] >= 'a' && id[i] <= 'f'))) {
          stop("INVALID_SESSION"); return;
        }
      }
      if (stableBlocked_ || rawBlocked_) { stop("IR_BLOCKED_AT_START"); return; }
      memcpy(session_, id, 33);
      lastContact_ = entered_ = now;
      state_ = State::RUNNING;
      motor_ = true;
      return;
    }
    if (strcmp(line, "BRIDGE:PING") == 0) { lastContact_ = now; return; }
    if (strncmp(line, "SORT:", 5) != 0 || webMode_) return;
    acceptLabel(line+5,now);
  }

  void acceptLabel(const char* labelText,uint32_t now) {
    const bool pausedWait = state_ == State::PAUSED && savedState_ == State::WAIT_AI;
    if(state_ != State::WAIT_AI && !pausedWait) return;
    if(pausedWait && deferred_)return;
    // At/after deadline even a syntactically valid late answer must not move this fruit.
    if (!pausedWait && elapsed(now, entered_) >= config_.aiTimeoutMs) return;
    Label label;
    if (strcmp(labelText, "GREEN") == 0) label = Label::GREEN;
    else if (strcmp(labelText, "RIPE") == 0) label = Label::RIPE;
    else if (strcmp(labelText, "REJECT") == 0) label = Label::REJECT;
    else { stop("INVALID_SORT"); return; }
    lastContact_ = now;
    if(pausedWait) { deferredLabel_=label; deferred_=true; return; }
    dispatch(label, now, false);
  }

  void tick(uint32_t now, bool irBlocked) {
    if (state_ == State::FAULT) return;
    if (irBlocked != rawBlocked_) { rawBlocked_ = irBlocked; rawChanged_ = now; }
    if (stableBlocked_ != rawBlocked_ && elapsed(now, rawChanged_) >= config_.debounceMs) {
      stableBlocked_ = rawBlocked_;
      if (!stableBlocked_) irArmed_ = true;
      else if (irArmed_) {
        irArmed_ = false;
        if (state_ == State::RUNNING) {
          if (counter_ == UINT32_MAX) { stop("COUNTER_EXHAUSTED"); return; }
          ++counter_;
          state_ = State::TO_CAMERA;
          entered_ = now;
        } else if (state_ != State::WAIT_BRIDGE && state_ != State::IDLE) {
          stop("SECOND_FRUIT"); return;
        }
      }
    }
    if (state_ != State::WAIT_BRIDGE && state_ != State::WAIT_AI && !timeoutDispatch_
        && elapsed(now, lastContact_) >= config_.heartbeatMs) {
      stop("BRIDGE_LOST"); return;
    }
    const uint32_t age = elapsed(now, entered_);
    switch (state_) {
      case State::TO_CAMERA:
        if (age >= config_.irToCameraMs) {
          motor_ = false;
          state_ = State::SETTLING;
          entered_ = now;
        }
        break;
      case State::SETTLING:
        if (age >= config_.settleMs) {
          state_ = State::WAIT_AI;
          entered_ = now;
          trigger_ = true;
        }
        break;
      case State::WAIT_AI:
        if (age >= config_.aiTimeoutMs) dispatch(Label::REJECT, now, true);
        break;
      case State::DISPATCH: {
        const uint32_t gateDelay = label_ == Label::GREEN ? config_.cameraToGate1Ms : config_.cameraToGate2Ms;
        if (label_ != Label::REJECT && !gateFired_ && age >= gateDelay) {
          if (age >= gateDelay + config_.gateHoldMs) { stop("MISSED_GATE"); return; }
          gateFired_ = true;
          gateStarted_ = now;
          if (label_ == Label::GREEN) gate1_ = 90;
          else gate2_ = 90;
        }
        if (gateFired_ && elapsed(now, gateStarted_) >= config_.gateHoldMs) gate1_ = gate2_ = 0;
        const uint32_t end = config_.cameraToGate2Ms + config_.gateHoldMs + config_.exitClearMs;
        if (age >= end && gate1_ == 0 && gate2_ == 0) {
          if (label_ == Label::GREEN) ++green_;
          else if (label_ == Label::RIPE) ++ripe_;
          else ++reject_;
          if (timeoutDispatch_) { stop("AI_TIMEOUT_CHECK_STATION"); return; }
          if (stableBlocked_ || rawBlocked_) { stop("IR_NOT_CLEAR"); return; }
          state_ = State::RUNNING;
          entered_ = now;
        }
        break;
      }
      default: break;
    }
  }

  bool takeTrigger() { bool pending = trigger_; trigger_ = false; return pending; }
  bool takeAck() { bool pending=ackPending_;ackPending_=false;return pending; }
  const char* ackId() const {return lastControl_;}
  const char* ackState() const {return ackState_;}
  State state() const { return state_; }
  bool motor() const { return motor_; }
  uint8_t gate1() const { return gate1_; }
  uint8_t gate2() const { return gate2_; }
  const char* session() const { return session_; }
  uint32_t counter() const { return counter_; }
  const char* fault() const { return fault_; }
  uint32_t green() const { return green_; }
  uint32_t ripe() const { return ripe_; }
  uint32_t rejected() const { return reject_; }

 private:
  static bool hex32(const char* s) {
    if(strlen(s)!=32)return false;
    for(int i=0;i<32;++i)if(!((s[i]>='0'&&s[i]<='9')||(s[i]>='a'&&s[i]<='f')))return false;
    return true;
  }
  void control(const char* text,uint32_t now) {
    char buffer[112];
    if(strlen(text)>=sizeof(buffer)){stop("CONTROL_FORMAT");return;}
    strcpy(buffer,text);
    char* action=strchr(buffer,':');
    if(!action){stop("CONTROL_FORMAT");return;} *action++=0;
    char* run=strchr(action,':');
    if(!run){stop("CONTROL_FORMAT");return;} *run++=0;
    if(!hex32(buffer)||!hex32(run)){stop("CONTROL_FORMAT");return;}
    if(strcmp(lastControl_,buffer)==0) {
      if(strcmp(lastAction_,action)!=0||strcmp(lastRun_,run)!=0){stop("CONTROL_ID_REUSED");return;}
      ackPending_=true;return;
    }
    strcpy(lastControl_,buffer);strncpy(lastAction_,action,7);lastAction_[7]=0;strcpy(lastRun_,run);
    strcpy(ackState_,"REJECTED");ackPending_=true;
    if(strcmp(action,"START")==0) {
      if(state_!=State::IDLE||stableBlocked_||rawBlocked_)return;
      strcpy(session_,run); counter_=0;trigger_=false;deferred_=false;timeoutDispatch_=false;
      gateFired_=false;gate1_=gate2_=0;state_=State::RUNNING;motor_=true;entered_=now;
      strcpy(ackState_,"RUNNING");
    } else {
      if(strcmp(action,"STOP")==0 && state_==State::IDLE){strcpy(ackState_,"IDLE");lastContact_=now;return;}
      if(strcmp(session_,run)!=0)return;
      if(strcmp(action,"PAUSE")==0 && state_!=State::IDLE && state_!=State::PAUSED && !timeoutDispatch_) {
        if(state_==State::WAIT_AI && elapsed(now,entered_)>=config_.aiTimeoutMs)return;
        savedState_=state_;pausedAt_=now;savedMotor_=motor_;state_=State::PAUSED;motor_=false;
        strcpy(ackState_,"PAUSED");
      } else if(strcmp(action,"RESUME")==0 && state_==State::PAUSED) {
        const uint32_t duration=elapsed(now,pausedAt_);
        entered_+=duration;gateStarted_+=duration;state_=savedState_;motor_=savedMotor_;
        if(deferred_){deferred_=false;dispatch(deferredLabel_,now,false);}
        strcpy(ackState_,"RUNNING");
      } else if(strcmp(action,"STOP")==0) {
        state_=State::IDLE;motor_=false;gate1_=gate2_=0;trigger_=false;deferred_=false;timeoutDispatch_=false;
        strcpy(ackState_,"IDLE");
      }
    }
    lastContact_=now;
  }
  static uint32_t elapsed(uint32_t now, uint32_t since) { return now - since; }
  void dispatch(Label label, uint32_t now, bool timedOut) {
    state_ = State::DISPATCH;
    entered_ = now;
    label_ = label;
    timeoutDispatch_ = timedOut;
    gateFired_ = false;
    gate1_ = gate2_ = 0;
    motor_ = true;
    trigger_ = false;
  }

  Config config_;
  State state_ = State::WAIT_BRIDGE;
  Label label_ = Label::REJECT;
  uint32_t entered_ = 0, lastContact_ = 0, rawChanged_ = 0, gateStarted_ = 0, counter_ = 0;
  uint32_t green_ = 0, ripe_ = 0, reject_ = 0;
  bool rawBlocked_ = false, stableBlocked_ = false, irArmed_ = true;
  bool motor_ = false, trigger_ = false, gateFired_ = false, timeoutDispatch_ = false;
  uint8_t gate1_ = 0, gate2_ = 0;
  char session_[33] = {};
  const char* fault_ = "";
  State savedState_ = State::RUNNING;
  uint32_t pausedAt_=0;
  bool savedMotor_=false,deferred_=false,ackPending_=false;
  Label deferredLabel_=Label::REJECT;
  char lastControl_[33]={},lastAction_[8]={},lastRun_[33]={},ackState_[16]={};
  bool webMode_=false;
};

}  // namespace autosort
