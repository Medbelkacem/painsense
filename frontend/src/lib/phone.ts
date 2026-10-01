// Mirrors the server's rule: a mobile is 05, 06 or 07 followed by eight digits, a landline is
// 0, a one-digit area code and seven digits; +213 or 00213 may replace the leading 0.
const MOBILE = /^0[5-7]\d{8}$/;
const LANDLINE = /^0[1-4]\d{7}$/;

export function normaliseAlgerianPhone(value: string): string | null {
  let digits = value.replace(/[\s().-]/g, '');
  if (!digits) return '';
  if (digits.startsWith('+213')) digits = `0${digits.slice(4)}`;
  else if (digits.startsWith('00213')) digits = `0${digits.slice(5)}`;
  return MOBILE.test(digits) || LANDLINE.test(digits) ? digits : null;
}

export function phoneError(value: string): string | null {
  if (!value.trim()) return null;
  return normaliseAlgerianPhone(value) === null
    ? 'Enter an Algerian number, such as 05 51 23 45 67 or 033 12 34 56.'
    : null;
}
