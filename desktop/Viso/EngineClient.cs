using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace Viso
{
    internal static class Json
    {
        public static Dictionary<string, object> Object(object value) { return value as Dictionary<string, object> ?? new Dictionary<string, object>(); }
        public static Dictionary<string, object> Child(this Dictionary<string, object> value, string key) { return Object(value.Get(key)); }
        public static object Get(this Dictionary<string, object> value, string key) { object result; return value.TryGetValue(key, out result) ? result : null; }
        public static string Text(this Dictionary<string, object> value, string key, string fallback = "") { return Convert.ToString(value.Get(key)) ?? fallback; }
        public static double Number(this Dictionary<string, object> value, string key) { return Convert.ToDouble(value.Get(key), System.Globalization.CultureInfo.InvariantCulture); }
        public static bool Flag(this Dictionary<string, object> value, string key) { return value.Get(key) is bool && (bool)value[key]; }
        public static Dictionary<string, object> Data(params object[] pairs)
        {
            var result = new Dictionary<string, object>();
            for (int i = 0; i < pairs.Length; i += 2) result[(string)pairs[i]] = pairs[i + 1];
            return result;
        }
        public static string Encode(object value) { return new JavaScriptSerializer { MaxJsonLength = 16000000 }.Serialize(value); }
        public static Dictionary<string, object> Decode(string value) { return Object(new JavaScriptSerializer { MaxJsonLength = 16000000 }.DeserializeObject(value)); }
    }

    internal sealed class EngineClient : IDisposable
    {
        private readonly Process process;
        private readonly StreamWriter input;
        private readonly object gate = new object();
        private readonly Dictionary<int, TaskCompletionSource<Dictionary<string, object>>> pending = new Dictionary<int, TaskCompletionSource<Dictionary<string, object>>>();
        private int sequence;
        private bool disposed;
        public event Action<Dictionary<string, object>> Event;

        public EngineClient(string root, bool ephemeral)
        {
            string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
            if (!File.Exists(python)) throw new FileNotFoundException("Run scripts\\setup.ps1 to prepare the recognition engine.");
            process = new Process { StartInfo = new ProcessStartInfo(python, "-u -m backend.viso.native" + (ephemeral ? " --ephemeral" : "")) {
                WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            }};
            process.StartInfo.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            process.Start();
            input = new StreamWriter(process.StandardInput.BaseStream, new UTF8Encoding(false)) { AutoFlush = true };
            // Drain model diagnostics without putting camera data or vectors in logs.
            process.ErrorDataReceived += delegate { };
            process.BeginErrorReadLine();
            Task.Run((Func<Task>)ReadLoop);
        }

        private async Task ReadLoop()
        {
            try
            {
                string line;
                while ((line = await process.StandardOutput.ReadLineAsync().ConfigureAwait(false)) != null)
                {
                    var message = Json.Decode(line);
                    if (message.Get("event") != null) { var handler = Event; if (handler != null) handler(message); continue; }
                    int id = Convert.ToInt32(message.Get("id"));
                    TaskCompletionSource<Dictionary<string, object>> completion;
                    lock (gate) { if (!pending.TryGetValue(id, out completion)) continue; pending.Remove(id); }
                    if (message.Get("error") != null) completion.TrySetException(new InvalidOperationException(message.Text("error")));
                    else completion.TrySetResult(message.Child("result"));
                }
                FailPending("Recognition engine closed. Restart Viso to reconnect.");
            }
            catch (Exception) { if (!disposed) FailPending("Recognition engine disconnected. Restart Viso to reconnect."); }
        }

        private void FailPending(string message)
        {
            lock (gate) { foreach (var item in pending.Values) item.TrySetException(new IOException(message)); pending.Clear(); }
            var handler = Event;
            if (!disposed && handler != null) handler(Json.Data("event", "engine_error", "message", message));
        }

        public async Task<Dictionary<string, object>> Send(string command, Dictionary<string, object> data = null)
        {
            var completion = new TaskCompletionSource<Dictionary<string, object>>(TaskCreationOptions.RunContinuationsAsynchronously);
            int id;
            lock (gate)
            {
                if (disposed || process.HasExited) throw new IOException("Recognition engine is closed. Restart Viso.");
                id = ++sequence;
                pending[id] = completion;
                try { input.WriteLine(Json.Encode(Json.Data("id", id, "command", command, "data", data ?? Json.Data()))); }
                catch { pending.Remove(id); throw; }
            }
            if (await Task.WhenAny(completion.Task, Task.Delay(30000)) != completion.Task)
            {
                // A timed-out mutation must not silently complete after the UI moves on.
                Dispose();
                throw new TimeoutException("Recognition engine timed out. Restart Viso.");
            }
            return await completion.Task;
        }

        public void Dispose()
        {
            lock (gate)
            {
                if (disposed) return;
                disposed = true;
                try { input.WriteLine("{\"command\":\"shutdown\"}"); input.Close(); } catch { }
                foreach (var item in pending.Values) item.TrySetCanceled();
                pending.Clear();
            }
            try { if (!process.WaitForExit(4000)) process.Kill(); process.WaitForExit(); } catch { }
            process.Dispose();
        }
    }
}
