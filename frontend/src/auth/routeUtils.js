/** Phase04: strict same-origin path routing; no external returnTo destinations. */
export const PUBLIC_ROUTES = Object.freeze(['/login', '/register', '/verify-email', '/forgot-password', '/reset-password', '/auth/2fa']);
export const USER_ROUTES = Object.freeze(['/dashboard', '/create/image', '/edit/image', '/create/video', '/edit/video', '/jobs', '/library', '/tools', '/presets', '/usage', '/workflows', '/workflows/new', '/account/profile', '/account/security', '/account/preferences', '/account/data']);
export const ADMIN_ROUTES = Object.freeze(['/admin', '/admin/infrastructure', '/admin/deployment-profiles', '/admin/models', '/admin/worker-images', '/admin/users', '/admin/audit-logs']);

export function safeReturnTo(input, fallback = '/dashboard') {
  if (typeof input !== 'string' || input.length > 1024 || !input.startsWith('/') || input.startsWith('//') || input.includes('\\') || /[\u0000-\u001f\u007f]/.test(input)) return fallback;
  try {
    const path = new URL(input, 'https://app.invalid');
    if (path.origin !== 'https://app.invalid' || path.username || path.password) return fallback;
    // Only user/app content can be a returnTo; never force-login into auth or admin via an untrusted link.
    if (!isUserPath(path.pathname)) return fallback;
    return path.pathname + path.search; // hash is never included; token fragments stay private.
  } catch { return fallback; }
}

export function isUserPath(path) {
  return /^\/models\/[A-Za-z0-9_-]{1,96}$/.test(path) || USER_ROUTES.includes(path) || /^\/jobs\/[A-Za-z0-9_-]{1,96}$/.test(path) || /^\/library\/[A-Za-z0-9_-]{1,96}$/.test(path) || /^\/workflows\/[A-Za-z0-9_-]{1,96}\/(?:versions|edit\/[A-Za-z0-9_-]{1,96})$/.test(path);
}
export function routeFor(path) {
  const normalized = (typeof path === 'string' ? path.replace(/\/+$/, '') || '/' : '/');
  if (normalized === '/') return {scope:'redirect', to:'/dashboard'};
  if (normalized === '/editor') return {scope:'redirect', to:'/create/image'};
  if (normalized === '/infrastructure') return {scope:'redirect', to:'/admin/infrastructure'};
  if (normalized === '/settings') return {scope:'redirect', to:'/admin/deployment-profiles'};
  if (/^\/admin\/users\/[A-Za-z0-9_-]{1,96}$/.test(normalized)) return {scope:'admin', path:normalized};
  if (/^\/models\/[A-Za-z0-9_-]{1,96}$/.test(normalized)) return {scope:'user',path:normalized};
  if (normalized === '/admin/jobs') return {scope:'admin', path:normalized};
  if (PUBLIC_ROUTES.includes(normalized)) return {scope:'public', path:normalized};
  if (isUserPath(normalized)) return {scope:'user', path:normalized};
  if (ADMIN_ROUTES.includes(normalized)) return {scope:'admin', path:normalized};
  return {scope:'missing', path:normalized};
}

export function isAdmin(user) {
  return Array.isArray(user?.roles) && ['admin', 'superadmin'].some(role => user.roles.includes(role));
}
export function maskedEmail(email) {
  const value = String(email || '');
  const at = value.lastIndexOf('@');
  if (at < 1) return '';
  const name = value.slice(0, at);
  return name[0] + '***@' + value.slice(at + 1);
}
