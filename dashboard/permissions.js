// Presentation only: the server independently checks every operation and session.
export const isAdminRole = user => user?.role === 'admin';
export const canOperate = user => isAdminRole(user) || user?.role === 'operator';
export const roleLabel = user => isAdminRole(user) ? 'Quản trị viên' : user?.role === 'operator' ? 'Nhân viên vận hành' : 'Khách · Demo công khai';
