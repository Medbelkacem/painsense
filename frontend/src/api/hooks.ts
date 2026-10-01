import { useCallback, useEffect, useState } from 'react';
import { ApiError, request } from './client';

interface Query<T> {
  data: T | null;
  error: string | null;
  /** True only on the first load, so a refresh does not blank the page. */
  loading: boolean;
  reload: () => void;
}

/**
 * Fetch a path and keep it current.
 *
 * `pollSeconds` exists because a sync run happens in a background worker: the page has
 * to notice a run finishing without the user reloading. Polling stops while the tab is
 * hidden, so a dashboard left open overnight is not still asking every ten seconds.
 */
export function useQuery<T>(path: string | null, pollSeconds = 0): Query<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [tick, setTick] = useState(0);

  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    if (path === null) return;
    const controller = new AbortController();
    request<T>(path, { signal: controller.signal })
      .then((payload) => {
        setData(payload);
        setError(null);
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof ApiError ? cause.message : 'Could not reach the server');
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [path, tick]);

  useEffect(() => {
    if (!pollSeconds || path === null) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) reload();
    }, pollSeconds * 1000);
    return () => window.clearInterval(timer);
  }, [pollSeconds, path, reload]);

  return { data, error, loading, reload };
}
