/** Bound both fetching and reading a response body; writes/uploads opt out. */
export async function withReadTimeout<T>(
  read: (signal: AbortSignal) => Promise<T>,
  timeoutMs = 30000,
): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      const error = new Error("The server took too long to respond. Please retry.");
      error.name = "TimeoutError";
      reject(error);
      controller.abort();
    }, timeoutMs);
  });
  try {
    return await Promise.race([read(controller.signal), timeout]);
  } finally {
    clearTimeout(timer!);
  }
}
