export const TEMPLATES_LIMIT_COOKIE = 'templates_limit';
export const PROTOCOLS_LIMIT_COOKIE = 'protocols_limit';
export const COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // 1 year
export const PAGINATION_LIMITS = [10, 20, 30, 40, 50];
export const DEFAULT_PAGINATION_LIMIT = 10;

/** Parse a raw cookie value into a valid page-size limit, falling back to the default. */
export function parseLimit(raw: string | undefined | null): number {
    const value = Number(raw);
    return PAGINATION_LIMITS.includes(value) ? value : DEFAULT_PAGINATION_LIMIT;
}
