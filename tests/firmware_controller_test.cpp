#include "../esp32-controller/AutoSortSerial/Controller.h"
#include <assert.h>
#include <iostream>
#include <string>

using autosort::Controller;
using autosort::State;
constexpr const char* READY = "BRIDGE:READY:0123456789abcdef0123456789abcdef";

struct Rig {
  Controller control;
  uint32_t now;
  bool blocked = false, heartbeat = true;
  explicit Rig(uint32_t start = 0) : now(start) { control.begin(now, false); }
  void advance(uint32_t ms) {
    for (uint32_t i = 0; i < ms; ++i) {
      ++now;
      if (heartbeat && now % 1000 == 0) control.command("BRIDGE:PING", now);
      control.tick(now, blocked);
    }
  }
  void ir(bool value) { blocked = value; control.tick(now, blocked); advance(20); }
  void arm() { control.command(READY, now); assert(control.motor()); }
  void waiting() {
    arm(); ir(true);
    assert(control.state() == State::TO_CAMERA);
    ir(false); advance(280);
    assert(control.state() == State::SETTLING && !control.motor());
    assert(!control.takeTrigger());
    advance(149); assert(!control.takeTrigger());
    advance(1);
    assert(control.state() == State::WAIT_AI && !control.motor());
    assert(control.takeTrigger() && !control.takeTrigger());
  }
};

void startup_and_rearm() {
  Rig r;
  r.advance(2000);
  assert(!r.control.motor() && !r.control.takeTrigger());
  r.control.command("SORT:GREEN", r.now);
  assert(!r.control.motor());
  r.arm();
  r.control.stop("TEST");
  r.control.command(READY, r.now);
  assert(!r.control.motor() && r.control.state() == State::FAULT);
  Rig blocked; blocked.ir(true); blocked.control.command(READY, blocked.now);
  assert(blocked.control.state() == State::FAULT && !blocked.control.motor());
}

void green_and_ripe_timing() {
  for (bool green : {true, false}) {
    Rig r; r.waiting();
    r.control.command(green ? "SORT:GREEN" : "SORT:RIPE", r.now);
    assert(r.control.motor());
    r.control.command("SORT:REJECT", r.now);  // duplicate/stray result cannot replace first result.
    r.advance(green ? 1199 : 2499);
    assert(r.control.gate1() == 0 && r.control.gate2() == 0);
    r.advance(1);
    assert((green ? r.control.gate1() : r.control.gate2()) == 90);
    r.advance(399);
    assert((green ? r.control.gate1() : r.control.gate2()) == 90);
    r.advance(1);
    assert(r.control.gate1() == 0 && r.control.gate2() == 0);
    r.advance(green ? 1800 : 500);
    assert(r.control.state() == State::RUNNING);
    assert((green ? r.control.green() : r.control.ripe()) == 1);
    assert(r.control.rejected() == 0);
    // New event only after the prior fruit has fully left the dispatch window.
    r.ir(true);
    assert(r.control.counter() == 2 && r.control.state() == State::TO_CAMERA);
  }
}

void reject_no_servo() {
  Rig r; r.waiting(); r.control.command("SORT:REJECT", r.now);
  for (int i = 0; i < 3400; ++i) {
    r.advance(1); assert(r.control.gate1() == 0 && r.control.gate2() == 0);
  }
  assert(r.control.rejected() == 1 && r.control.state() == State::RUNNING);
}

void timeout_latches_and_ignores_late_sort() {
  Rig r; r.waiting(); r.heartbeat = false;
  r.advance(29999);
  assert(r.control.state() == State::WAIT_AI);
  r.advance(1);
  assert(r.control.state() == State::DISPATCH && r.control.motor());
  r.control.command("SORT:GREEN", r.now);
  r.advance(3400);
  assert(r.control.state() == State::FAULT && !r.control.motor());
  assert(r.control.rejected() == 1 && r.control.green() == 0);
  r.control.command(READY, r.now);
  assert(r.control.state() == State::FAULT);
  Rig deadline; deadline.waiting();
  deadline.now += 30000;
  deadline.control.command("SORT:RIPE", deadline.now);
  deadline.control.tick(deadline.now, false);
  assert(deadline.control.state() == State::DISPATCH);
  deadline.advance(3400);
  assert(deadline.control.rejected() == 1 && deadline.control.ripe() == 0);
}

void second_fruit_and_noise() {
  Rig r; r.waiting(); r.ir(true);
  assert(r.control.state() == State::FAULT && !r.control.motor());
  Rig noise; noise.arm();
  noise.blocked = true; noise.control.tick(noise.now, true); noise.advance(19);
  noise.blocked = false; noise.control.tick(noise.now, false); noise.advance(20);
  assert(noise.control.counter() == 0 && noise.control.state() == State::RUNNING);
  Rig invalid; invalid.waiting(); invalid.control.command("SORT:MOCK", invalid.now);
  assert(invalid.control.state() == State::FAULT && !invalid.control.motor());
}

void heartbeat_and_missed_gate() {
  Rig lost; lost.arm(); lost.heartbeat = false; lost.advance(5000);
  assert(lost.control.state() == State::FAULT && !lost.control.motor());
  Rig missed; missed.waiting(); missed.control.command("SORT:GREEN", missed.now);
  missed.now += 1600; missed.control.tick(missed.now, false);
  assert(missed.control.state() == State::FAULT && missed.control.gate1() == 0);
  Rig stopped; stopped.waiting(); stopped.control.command("SORT:RIPE", stopped.now);
  stopped.advance(2500); stopped.control.command("BRIDGE:STOP", stopped.now);
  assert(stopped.control.gate2() == 0 && !stopped.control.motor());
}

void wrap_and_session_validation() {
  Rig wrapped(UINT32_MAX - 100); wrapped.waiting();
  wrapped.control.command("SORT:RIPE", wrapped.now); wrapped.advance(3400);
  assert(wrapped.control.ripe() == 1 && wrapped.control.state() == State::RUNNING);
  for (const char* line : {"BRIDGE:READY:bad", "BRIDGE:READY:0123456789abcdef0123456789abcdeg"}) {
    Rig r; r.control.command(line, r.now);
    assert(r.control.state() == State::FAULT && !r.control.motor());
  }
}

constexpr const char* RUN1="11111111111111111111111111111111";
constexpr const char* RUN2="22222222222222222222222222222222";
void control(Rig& r,const char* id,const char* action,const char* run=RUN1) {
  std::string line=std::string("CONTROL:")+id+":"+action+":"+run;
  r.control.command(line.c_str(),r.now);
  assert(r.control.takeAck());
}
constexpr const char* CMD1="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
constexpr const char* CMD2="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
constexpr const char* CMD3="cccccccccccccccccccccccccccccccc";
constexpr const char* CMD4="dddddddddddddddddddddddddddddddd";

void web_standby_start_stop_and_dedup() {
  Rig failed;failed.control.command("BRIDGE:CONNECT",failed.now);
  std::string start=std::string("CONTROL:")+CMD1+":START:"+RUN1;
  failed.control.command(start.c_str(),failed.now);failed.control.stop("SIMULATED_OUTPUT_FAULT");
  assert(!failed.control.takeAck()); // Never ACK RUNNING after a fault before outputs are applied.
  Rig idle;idle.control.command("BRIDGE:CONNECT",idle.now);control(idle,CMD2,"STOP");
  assert(idle.control.state()==State::IDLE&&!idle.control.motor());
  Rig r;r.control.command("BRIDGE:CONNECT",r.now);r.advance(2000);
  assert(r.control.state()==State::IDLE&&!r.control.motor());
  control(r,CMD1,"START");assert(r.control.state()==State::RUNNING&&r.control.motor());
  r.ir(true);assert(r.control.counter()==1);
  control(r,CMD1,"START");assert(r.control.counter()==1); // Exact retry never restarts movement or run.
  control(r,CMD2,"STOP");assert(r.control.state()==State::IDLE&&!r.control.motor());
  r.ir(false);control(r,CMD3,"START",RUN2);assert(r.control.counter()==0);
  control(r,CMD4,"STOP",RUN1);assert(std::string(r.control.ackState())=="REJECTED");
  assert(r.control.state()==State::RUNNING&&r.control.motor());
}

void pause_freezes_travel_and_gate_time() {
  Rig r;r.control.command("BRIDGE:CONNECT",r.now);control(r,CMD1,"START");
  r.ir(true);r.ir(false);r.advance(280+150);assert(r.control.takeTrigger());
  std::string result=std::string("RESULT:")+RUN1+":1:GREEN";
  r.control.command(result.c_str(),r.now);r.advance(1000);
  control(r,CMD2,"PAUSE");assert(!r.control.motor());r.advance(20000);
  assert(r.control.gate1()==0&&r.control.state()==State::PAUSED);
  control(r,CMD3,"RESUME");r.advance(199);assert(r.control.gate1()==0);
  r.advance(1);assert(r.control.gate1()==90);
  control(r,CMD4,"PAUSE");r.advance(10000);assert(r.control.gate1()==90);
  control(r,CMD1,"RESUME");r.advance(399);assert(r.control.gate1()==90);
  r.advance(1);assert(r.control.gate1()==0);
}

void paused_ai_never_restarts_motor_and_old_results_are_ignored() {
  Rig r;r.control.command("BRIDGE:CONNECT",r.now);control(r,CMD1,"START");
  r.ir(true);r.ir(false);r.advance(430);assert(r.control.takeTrigger());
  control(r,CMD2,"PAUSE");r.advance(35000);
  std::string result=std::string("RESULT:")+RUN1+":1:RIPE";
  r.control.command(result.c_str(),r.now);
  assert(r.control.state()==State::PAUSED&&!r.control.motor());
  control(r,CMD3,"RESUME");assert(r.control.state()==State::DISPATCH&&r.control.motor());
  control(r,CMD4,"STOP");control(r,CMD1,"START",RUN2);
  r.ir(true);r.ir(false);r.advance(430);assert(r.control.takeTrigger());
  r.control.command(result.c_str(),r.now);
  assert(r.control.state()==State::WAIT_AI&&!r.control.motor());
  r.control.command("SORT:GREEN",r.now); // Legacy unscoped results disabled in web mode.
  assert(r.control.state()==State::WAIT_AI);
}

int main() {
  startup_and_rearm(); green_and_ripe_timing(); reject_no_servo();
  timeout_latches_and_ignores_late_sort(); second_fruit_and_noise();
  heartbeat_and_missed_gate(); wrap_and_session_validation();
  web_standby_start_stop_and_dedup();pause_freezes_travel_and_gate_time();
  paused_ai_never_restarts_motor_and_old_results_are_ignored();
  std::cout << "Firmware controller: all state/timing/failure scenarios passed\n";
}
