import { useState, useEffect, useCallback } from "react";
import axios from "axios";
import type { Job } from "../types/job";

const API = "/api/jobs";

export function useJob(jobId: string, pollInterval = 3000) {
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const { data } = await axios.get<Job>(`${API}/${jobId}`);
      setJob(data);
      setError(null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    fetch();
    if (pollInterval <= 0) return;
    const interval = setInterval(fetch, pollInterval);
    return () => clearInterval(interval);
  }, [fetch, pollInterval]);

  return { job, loading, error, refresh: fetch };
}

export function useJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    try {
      const { data } = await axios.get<Job[]>(API);
      setJobs(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetch();
  }, [fetch]);

  return { jobs, loading, refresh: fetch };
}
