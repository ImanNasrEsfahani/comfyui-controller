/** Phase04: cookie-only Auth API; no browser bearer/admin token. */
export class ApiError extends Error {
  constructor(status, message, code = '') { super(message); this.name='ApiError'; this.status=status; this.code=code; }
}
export const ERROR_LABELS = Object.freeze({
  400:'درخواست نامعتبر است.', 401:'نشست معتبر نیست؛ دوباره وارد شوید.',
  403:'مجوز دسترسی وجود ندارد.', 404:'مورد موردنظر پیدا نشد.',
  409:'این لینک منقضی یا قبلاً استفاده شده است.', 410:'لینک منقضی شده است.',
  422:'اطلاعات فرم را بررسی کنید.', 429:'تعداد تلاش‌ها زیاد بوده؛ بعداً دوباره امتحان کنید.',
  500:'خطای سرور؛ بعداً دوباره تلاش کنید.', 502:'اتصال به سرویس برقرار نشد.',
  503:'این قابلیت هنوز روی سرور فعال نشده است.'
});
export function messageForStatus(status) { return ERROR_LABELS[status] || 'درخواست انجام نشد. دوباره امتحان کنید.'; }

/** Browser fetch does not send Origin on GET, but same-origin POST must have Origin for backend protection. */
export async function authRequest(endpoint, {method='GET', body, csrfToken, signal, fetchImpl=globalThis.fetch} = {}) {
  if (!/^\/(session|me|csrf|register|login|logout|logout-all|verify-email|resend-verification|forgot-password|reset-password|change-password|sessions)(\/[^/?#]+)?$/.test(endpoint)) {
    throw new Error('Endpoint not permitted for auth client');
  }
  const action = method.toUpperCase();
  const headers={Accept:'application/json'};
  if (body !== undefined) headers['Content-Type']='application/json';
  if (csrfToken) headers['X-CSRF-Token']=csrfToken;
  const response=await fetchImpl(`/api/auth${endpoint}`, {method:action, headers, credentials:'same-origin', cache:'no-store', signal,
    ...(body!==undefined ? {body:JSON.stringify(body)} : {})});
  let data=null;
  if (response.status!==204) { try {data=await response.json();} catch {data=null;} }
  if (!response.ok) throw new ApiError(response.status,messageForStatus(response.status),data?.error?.code || '');
  return data;
}
