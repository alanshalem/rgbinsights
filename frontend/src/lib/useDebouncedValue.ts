import { useEffect, useState } from 'react';

/** Returns `value` delayed by `delayMs`, resetting the timer on each change.
 * Used to keep the search box responsive while the derived queries (users +
 * counts) only refetch once the user pauses typing. */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}
