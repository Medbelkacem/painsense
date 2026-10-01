import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** Join class names, letting a caller's utility win over a component default. */
export function cx(...parts: ClassValue[]): string {
  return twMerge(clsx(parts));
}
