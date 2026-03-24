import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Convert a UTC cron expression's hour/minute fields to local time.
 * Only handles simple numeric hour/minute (not ranges or steps).
 * Returns the original string if it can't convert.
 */
export function cronUtcToLocal(cron: string): string {
  const parts = cron.split(/\s+/);
  if (parts.length < 5) return cron;
  const [min, hour, ...rest] = parts;
  const utcH = parseInt(hour, 10);
  const utcM = parseInt(min, 10);
  if (isNaN(utcH) || isNaN(utcM)) return cron;
  const d = new Date();
  d.setUTCHours(utcH, utcM, 0, 0);
  return `${d.getMinutes()} ${d.getHours()} ${rest.join(" ")}`;
}

/**
 * Convert a local-time cron expression's hour/minute fields to UTC.
 * Only handles simple numeric hour/minute (not ranges or steps).
 * Returns the original string if it can't convert.
 */
export function cronLocalToUtc(cron: string): string {
  const parts = cron.split(/\s+/);
  if (parts.length < 5) return cron;
  const [min, hour, ...rest] = parts;
  const localH = parseInt(hour, 10);
  const localM = parseInt(min, 10);
  if (isNaN(localH) || isNaN(localM)) return cron;
  const d = new Date();
  d.setHours(localH, localM, 0, 0);
  return `${d.getUTCMinutes()} ${d.getUTCHours()} ${rest.join(" ")}`;
}
