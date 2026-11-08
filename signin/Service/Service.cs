using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace Viso.SignIn
{
    internal sealed class Account
    {
        public string Sid, Kind, Qualified, Password, Profile, Revision;
        public int Camera;
        public void Forget() { Password = null; Profile = null; }
    }

    internal sealed class Vault
    {
        private readonly string folder;
        public readonly SemaphoreSlim Gate = new SemaphoreSlim(1, 1);
        private readonly Dictionary<string, long> versions = new Dictionary<string, long>();
        public Vault(string folder) { this.folder = folder; }
        // Call under Gate. Even an unlink of an absent record invalidates a pending link.
        public long Version(string sid) { long version; return versions.TryGetValue(sid, out version) ? version : 0; }
        private string PathFor(string sid) { return Path.Combine(folder, new SecurityIdentifier(sid).Value + ".dpapi"); }
        public Account Load(string sid)
        {
            string path = PathFor(sid);
            if (!File.Exists(path)) return null;
            if (new FileInfo(path).Length > Wire.Limit) throw new InvalidDataException("Invalid account record.");
            byte[] clear = ProtectedData.Unprotect(File.ReadAllBytes(path), null, DataProtectionScope.LocalMachine);
            try {
                var account = new JavaScriptSerializer().Deserialize<Account>(Encoding.UTF8.GetString(clear));
                if (account == null || account.Sid != sid || account.Qualified != Native.AccountName(account.Kind, account.Qualified) || string.IsNullOrEmpty(account.Revision) || string.IsNullOrEmpty(account.Password) || account.Password.Length > 256 || account.Camera < 0 || account.Camera > 32) throw new InvalidDataException("Invalid account binding.");
                return account;
            } finally { Array.Clear(clear, 0, clear.Length); }
        }
        public void Save(Account account)
        {
            byte[] clear = Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(account));
            try {
                byte[] encrypted = ProtectedData.Protect(clear, null, DataProtectionScope.LocalMachine);
                string path = PathFor(account.Sid), temporary = path + ".new";
                try {
                    File.WriteAllBytes(temporary, encrypted);
                    if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
                    versions[account.Sid] = Version(account.Sid) + 1;
                } finally { if (File.Exists(temporary)) File.Delete(temporary); }
            } finally { Array.Clear(clear, 0, clear.Length); }
        }
        public void Delete(string sid) { File.Delete(PathFor(sid)); versions[sid] = Version(sid) + 1; }
        public void SaveIfCurrent(Account account, long version)
        {
            if (Version(account.Sid) != version) throw new InvalidOperationException("Account link changed while linking. Start again in Viso Settings.");
            Save(account);
        }
        public bool IsCurrent(Account account)
        {
            var current = Load(account.Sid);
            try { return current != null && current.Revision == account.Revision; }
            finally { if (current != null) current.Forget(); }
        }
    }

    // Killing/closing the service also closes the camera worker, including after a crash.
    internal sealed class Worker : IDisposable
    {
        private readonly Process process;
        private readonly StreamWriter input;
        private IntPtr job;
        private int disposed;
        internal int ProcessId { get { return process.Id; } }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr CreateJobObject(IntPtr security, string name);
        [DllImport("kernel32.dll")] private static extern bool SetInformationJobObject(IntPtr job, int info, ref Limits limits, uint length);
        [DllImport("kernel32.dll")] private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [StructLayout(LayoutKind.Sequential)] private struct Basic { public long ProcessTime, JobTime; public uint Flags; public UIntPtr Min, Max; public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling; }
        [StructLayout(LayoutKind.Sequential)] private struct Io { public ulong Read, Write, Other, ReadBytes, WriteBytes, OtherBytes; }
        [StructLayout(LayoutKind.Sequential)] private struct Limits { public Basic Basic; public Io Io; public UIntPtr Process, Job, PeakProcess, PeakJob; }
        public Worker(string root)
        {
            job = CreateJobObject(IntPtr.Zero, null);
            var limits = new Limits(); limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (job == IntPtr.Zero || !SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(typeof(Limits)))) { Dispose(); throw new IOException("Cannot isolate the camera worker."); }
            process = new Process { StartInfo = new ProcessStartInfo(Path.Combine(root, "runtime", "python.exe"), "-I -B -u \"" + Path.Combine(root, "backend", "viso", "signin.py") + "\"") {
                WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            }};
            process.StartInfo.EnvironmentVariables["PATH"] = Path.Combine(root, "runtime") + ";" + Environment.GetFolderPath(Environment.SpecialFolder.System);
            try {
                process.Start();
                if (!AssignProcessToJobObject(job, process.Handle)) throw new IOException("Cannot contain the camera worker.");
                process.ErrorDataReceived += delegate { }; process.BeginErrorReadLine();
                input = new StreamWriter(process.StandardInput.BaseStream, new UTF8Encoding(false)) { AutoFlush = true };
            } catch { Dispose(); throw; }
        }
        public void Start(Account account, string command)
        {
            var serializer = new JavaScriptSerializer { MaxJsonLength = Wire.Limit };
            input.WriteLine(serializer.Serialize(new { command = command, profile = serializer.DeserializeObject(account.Profile), camera = account.Camera }));
        }
        public async Task<Dictionary<string, object>> Next()
        {
            var line = await process.StandardOutput.ReadLineAsync().ConfigureAwait(false);
            if (line == null || line.Length > Wire.Limit) throw new IOException("Recognition worker stopped.");
            return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(line);
        }
        public void Ack() { input.WriteLine("ack"); }
        public void Dispose()
        {
            if (Interlocked.Exchange(ref disposed, 1) != 0) return;
            if (job != IntPtr.Zero) { Native.CloseHandle(job); job = IntPtr.Zero; }
            if (process != null) {
                try { if (!process.HasExited) process.Kill(); process.WaitForExit(2000); } catch (InvalidOperationException) { }
                process.Dispose();
            }
            if (input != null) { try { input.Dispose(); } catch (IOException) { } }
        }
    }

    internal sealed class SignInService : ServiceBase
    {
        private readonly string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        private readonly Vault vault = new Vault(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "Viso", "Accounts"));
        private readonly SemaphoreSlim camera = new SemaphoreSlim(1, 1);
        private readonly HashSet<NamedPipeServerStream> connections = new HashSet<NamedPipeServerStream>();
        private readonly HashSet<Worker> workers = new HashSet<Worker>();
        private volatile bool stopping;
        public SignInService() { ServiceName = "VisoSignIn"; CanShutdown = true; }
        protected override void OnStart(string[] args)
        {
            if (!WindowsIdentity.GetCurrent().IsSystem || !root.Equals(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Viso"), StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Install Viso sign-in into Program Files and run it through Windows Services.");
            for (int i = 0; i < 8; i++) Task.Run((Func<Task>)Listen);
        }
        protected override void OnStop()
        {
            lock (connections) { stopping = true; foreach (var pipe in connections) pipe.Dispose(); }
            lock (workers) { foreach (var worker in workers) worker.Dispose(); workers.Clear(); }
        }
        protected override void OnShutdown() { OnStop(); }
        internal static PipeSecurity PipePermissions()
        {
            var security = new PipeSecurity();
            security.SetAccessRuleProtection(true, false);
            security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.NetworkSid, null), PipeAccessRights.FullControl, AccessControlType.Deny));
            security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null), PipeAccessRights.FullControl, AccessControlType.Allow));
            // WriteData, not CreateNewInstance: clients cannot impersonate a server instance.
            security.AddAccessRule(new PipeAccessRule(new SecurityIdentifier(WellKnownSidType.AuthenticatedUserSid, null), PipeAccessRights.ReadWrite, AccessControlType.Allow));
            return security;
        }
        private async Task Listen()
        {
            while (!stopping) {
                NamedPipeServerStream pipe = null;
                try {
                    pipe = new NamedPipeServerStream(Wire.PipeName, PipeDirection.InOut, 8, PipeTransmissionMode.Byte, PipeOptions.Asynchronous, 4096, 4096, PipePermissions());
                    lock (connections) { if (stopping) { pipe.Dispose(); return; } connections.Add(pipe); }
                    await pipe.WaitForConnectionAsync().ConfigureAwait(false);
                    using (var deadline = new Timer(delegate { try { pipe.Dispose(); } catch { } }, null, 65000, Timeout.Infinite))
                        await Handle(pipe).ConfigureAwait(false);
                } catch (Exception) { }
                finally { if (pipe != null) { lock (connections) connections.Remove(pipe); pipe.Dispose(); } }
                if (!stopping) await Task.Delay(200).ConfigureAwait(false);
            }
        }
        private async Task Handle(NamedPipeServerStream pipe)
        {
            string[] request = null; string failure = null;
            try {
                request = await Wire.Receive(pipe).ConfigureAwait(false);
                var caller = Native.Identify(pipe);
                if (request[0] == "verify") {
                    caller.RequireLogonUI();
                    if (request.Length != 4) throw new InvalidDataException();
                    if (!await camera.WaitAsync(0).ConfigureAwait(false)) throw new InvalidOperationException("The camera is already being used by another sign-in attempt.");
                    try { await Verify(pipe, request).ConfigureAwait(false); } finally { camera.Release(); }
                    return;
                }
                if (caller.System) throw new UnauthorizedAccessException("Link accounts from your signed-in desktop.");
                if (request[0] == "status" && request.Length == 1) {
                    Account account;
                    await vault.Gate.WaitAsync().ConfigureAwait(false);
                    try { account = vault.Load(caller.Sid); } finally { vault.Gate.Release(); }
                    try { await Wire.Send(pipe, "ok", account == null ? "Not linked" : "Linked: " + account.Qualified, account == null ? "" : account.Kind).ConfigureAwait(false); }
                    finally { if (account != null) account.Forget(); }
                } else if (request[0] == "unlink" && request.Length == 1) {
                    await vault.Gate.WaitAsync().ConfigureAwait(false);
                    try { vault.Delete(caller.Sid); } finally { vault.Gate.Release(); }
                    await Wire.Send(pipe, "ok", "Windows face sign-in disabled for this account.").ConfigureAwait(false);
                } else if (request[0] == "link" && request.Length == 6) {
                    long version;
                    await vault.Gate.WaitAsync().ConfigureAwait(false);
                    try { version = vault.Version(caller.Sid); } finally { vault.Gate.Release(); }
                    string qualified = Native.AccountName(request[1], request[2]);
                    Native.ValidatePassword(qualified, request[3], caller.Sid);
                    int index;
                    if (!int.TryParse(request[5], out index) || index < 0 || index > 32 || request[4].Length > 65536) throw new InvalidDataException("Invalid enrollment settings.");
                    var account = new Account { Sid = caller.Sid, Kind = request[1], Qualified = qualified, Password = request[3], Profile = request[4], Camera = index, Revision = Guid.NewGuid().ToString("N") };
                    try {
                        await WithWorker(account, "validate", async delegate(Worker worker) {
                            var result = await worker.Next().ConfigureAwait(false);
                            if (Convert.ToString(result["event"]) != "validated") throw new InvalidOperationException(Convert.ToString(result["message"]));
                        }).ConfigureAwait(false);
                        await vault.Gate.WaitAsync().ConfigureAwait(false);
                        try { if (stopping) throw new OperationCanceledException(); vault.SaveIfCurrent(account, version); }
                        finally { vault.Gate.Release(); }
                    } finally { account.Forget(); }
                    await Wire.Send(pipe, "ok", "Linked: " + qualified).ConfigureAwait(false);
                } else throw new InvalidDataException("Unknown sign-in request.");
            } catch (Exception error) {
                failure = error is InvalidOperationException || error is ArgumentException || error is UnauthorizedAccessException ? error.Message : "Windows face sign-in could not complete. Use another sign-in option and check Viso Settings.";
            } finally { if (request != null) Array.Clear(request, 0, request.Length); }
            if (failure != null) { try { await Wire.Send(pipe, "error", failure).ConfigureAwait(false); } catch { } }
        }
        private async Task WithWorker(Account account, string command, Func<Worker, Task> action)
        {
            Worker worker;
            lock (workers) { if (stopping) throw new OperationCanceledException(); worker = new Worker(root); workers.Add(worker); }
            try {
                worker.Start(account, command);
                var task = action(worker);
                if (await Task.WhenAny(task, Task.Delay(command == "verify" ? 45000 : 20000)).ConfigureAwait(false) != task) {
                    ObserveFailure(task);
                    throw new System.TimeoutException("Recognition timed out.");
                }
                await task.ConfigureAwait(false);
            } finally { lock (workers) { if (workers.Remove(worker)) worker.Dispose(); } }
        }
        internal static bool Matches(Account account, string sid, string kind, string qualified)
        {
            return account != null && account.Sid == sid && account.Kind == kind && string.Equals(account.Qualified, qualified, StringComparison.OrdinalIgnoreCase);
        }
        private static void ObserveFailure(Task task)
        {
            task.ContinueWith(delegate(Task failed) { var ignored = failed.Exception; }, TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously);
        }
        internal static async Task Relay(Stream pipe, Func<Task<Dictionary<string, object>>> nextEvent, Action acknowledge)
        {
            // Keep a read pending even while inference is silent, so closing
            // LogonUI's pipe promptly kills the worker and frees the camera.
            var peer = Wire.Receive(pipe); ObserveFailure(peer);
            while (true) {
                var next = nextEvent(); ObserveFailure(next);
                if (await Task.WhenAny(next, peer).ConfigureAwait(false) == peer || peer.IsCompleted) throw new OperationCanceledException();
                var result = await next.ConfigureAwait(false);
                string kind = Convert.ToString(result["event"]);
                if (kind == "accepted") return;
                string message = result.ContainsKey("message") ? Convert.ToString(result["message"]) : "Face verification failed.";
                if (kind == "error") throw new InvalidOperationException(message);
                if (kind != "status" && kind != "prompt") throw new InvalidDataException();
                await Wire.Send(pipe, kind, message).ConfigureAwait(false);
                var ack = await peer.ConfigureAwait(false);
                if (ack.Length != 1 || ack[0] != "ack") throw new OperationCanceledException();
                peer = Wire.Receive(pipe); ObserveFailure(peer);
                if (kind == "prompt") acknowledge();
            }
        }
        private async Task Verify(NamedPipeServerStream pipe, string[] request)
        {
            Account account;
            await vault.Gate.WaitAsync().ConfigureAwait(false);
            try { account = vault.Load(request[1]); } finally { vault.Gate.Release(); }
            try {
                if (!Matches(account, request[1], request[2], request[3])) throw new InvalidOperationException("Open Viso Settings in this Windows account and link Windows sign-in first.");
                await WithWorker(account, "verify", worker => Relay(pipe, worker.Next, worker.Ack)).ConfigureAwait(false);
                if (stopping) throw new UnauthorizedAccessException();
                // Re-read after recognition so unlink/relink revokes in-flight attempts.
                await vault.Gate.WaitAsync().ConfigureAwait(false);
                try {
                    if (stopping || !vault.IsCurrent(account)) throw new UnauthorizedAccessException("Account link changed. Start a new sign-in attempt.");
                    await Wire.Send(pipe, "credential", account.Kind, account.Qualified, account.Password).ConfigureAwait(false);
                } finally { vault.Gate.Release(); }
            } finally { if (account != null) account.Forget(); }
        }
        public static void Main() { ServiceBase.Run(new SignInService()); }
    }
}
