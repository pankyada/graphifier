"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { isAbortError, messageOf } from "./api";

interface ResourceState<T> {
  key: string | null;
  data: T | null;
  error: string | null;
  status: number;
  loading: boolean;
}

export interface Resource<T> {
  data: T | null;
  error: string | null;
  /** HTTP status of the last failure (0 = network unreachable). */
  status: number;
  loading: boolean;
  reload: () => void;
}

/**
 * Keyed async resource. A new key starts a fresh request and aborts the
 * previous one, so stale responses never overwrite newer selections. A reload
 * with the same key keeps the previous data on screen while refetching.
 * A null key disables the resource.
 */
export function useResource<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>): Resource<T> {
  const [state, setState] = useState<ResourceState<T>>({
    key: null,
    data: null,
    error: null,
    status: 0,
    loading: false,
  });
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(load);

  useEffect(() => {
    loaderRef.current = load;
  });

  useEffect(() => {
    if (key === null) {
      setState({ key: null, data: null, error: null, status: 0, loading: false });
      return;
    }
    const controller = new AbortController();
    setState((prev) => ({
      key,
      data: prev.key === key ? prev.data : null,
      error: null,
      status: 0,
      loading: true,
    }));
    loaderRef.current(controller.signal).then(
      (data) => {
        setState({ key, data, error: null, status: 0, loading: false });
      },
      (error: unknown) => {
        if (isAbortError(error)) return;
        const status = typeof (error as { status?: unknown })?.status === "number" ? (error as { status: number }).status : 0;
        setState((prev) => ({
          key,
          data: prev.key === key ? prev.data : null,
          error: messageOf(error),
          status,
          loading: false,
        }));
      },
    );
    return () => controller.abort();
  }, [key, tick]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  const current = state.key === key;
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    status: current ? state.status : 0,
    loading: key !== null && (!current || state.loading),
    reload,
  };
}
