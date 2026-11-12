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
        private readonly Task initialized;
        internal int ProcessId { get { return process.Id; } }
        internal Task Ready { get { return initialized; } }
        internal bool IsAlive { get { try { return disposed == 0 && !process.HasExited; } catch { return false; } } }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr CreateJobObject(IntPtr security, string name);
        [DllImport("kernel32.dll")] private static extern bool SetInformationJobObject(IntPtr job, int info, ref Limits limits, uint length);
        [DllImport("kernel32.dll")] private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [StructLayout(LayoutKind.Sequential)] private struct Basic { public long ProcessTime, JobTime; public uint Flags; public UIntPtr Min, Max; public uint Active; public UIntPtr Affinity; public uint Priority, Scheduling; }
        [StructLayout(LayoutKind.Sequential)] private struct Io { public ulong Read, Write, Other, ReadBytes, WriteBytes, OtherBytes; }
        [StructLayout(LayoutKind.Sequential)] private struct Limits { public Basic Basic; public Io Io; public UIntPtr Process, Job, PeakProcess, PeakJob; }
        public Worker(string root, bool prewarm = false)
        {
            job = CreateJobObject(IntPtr.Zero, null);
            var limits = new Limits(); limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (job == IntPtr.Zero || !SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(typeof(Limits)))) { Dispose(); throw new IOException("Cannot isolate the camera worker."); }
            process = new Process { StartInfo = new ProcessStartInfo(Path.Combine(root, "runtime", "python.exe"), "-I -B -u \"" + Path.Combine(root, "backend", "viso", "signin.py") + "\"" + (prewarm ? " --prewarm" : "")) {
                WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            }};
            process.StartInfo.EnvironmentVariables["PATH"] = Path.Combine(root, "runtime") + ";" + Environment.GetFolderPath(Environment.SpecialFolder.System);
            try {
                process.Start();
                if (!AssignProcessToJobObject(job, process.Handle)) throw new IOException("Cannot contain the camera worker.");
                process.ErrorDataReceived += delegate { }; process.BeginErrorReadLine();
                input = new StreamWriter(process.StandardInput.BaseStream, new UTF8Encoding(false)) { AutoFlush = true };
                initialized = prewarm ? Initialize() : Task.FromResult(0);
                initialized.ContinueWith(delegate(Task failed) { var ignored = failed.Exception; }, TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously);
            } catch { Dispose(); throw; }
        }
        public void Start(Account account, string command)
        {
            var serializer = new JavaScriptSerializer { MaxJsonLength = Wire.Limit };
            input.WriteLine(serializer.Serialize(new { command = command, profile = serializer.DeserializeObject(account.Profile), camera = account.Camera }));
        }
        private async Task<Dictionary<string, object>> ReadEvent()
        {
            var line = await process.StandardOutput.ReadLineAsync().ConfigureAwait(false);
            if (line == null || line.Length > Wire.Limit) throw new IOException("Recognition worker stopped.");
            return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(line);
        }
        private async Task Initialize()
        {
            var ready = await ReadEvent().ConfigureAwait(false);
            if (Convert.ToString(ready["event"]) != "ready") throw new IOException("Recognition models could not initialize.");
        }
        public async Task<Dictionary<string, object>> Next()
        {
            await initialized.ConfigureAwait(false);
            return await ReadEvent().ConfigureAwait(false);
        }
        public void Ack() { input.WriteLine("ack"); }
        public void Dispose()
        {
            if (Interlocked.Exchange(ref disposed, 1) != 0) return;
            if (job != IntPtr.Zero) { Native.CloseHandle(job); job = IntPtr.Zero; }
            if (process != null) {
                try { if (!process.HasExited) process.Kill(); process.WaitForExit(2000); }
                catch (InvalidOperationException) { }
                catch (System.ComponentModel.Win32Exception) { /* Job close already revoked the process. */ }
                process.Dispose();
            }
            if (input != null) { try { input.Dispose(); } catch (IOException) { } }
        }
    }

    internal sealed class SignInService : ServiceBase
    {
        internal const int BootStandbyLeaseMilliseconds = 300000;
        private readonly string root;
        private readonly Vault vault = new Vault(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "Viso", "Accounts"));
        private readonly SemaphoreSlim camera = new SemaphoreSlim(1, 1);
        private readonly HashSet<NamedPipeServerStream> connections = new HashSet<NamedPipeServerStream>();
        private readonly HashSet<Worker> workers = new HashSet<Worker>();
        private Worker standby;
        private readonly Timer standbyExpiry;
        private readonly int standbyLeaseMilliseconds;
        private long standbyDeadline;
        private volatile bool stopping;
        private volatile bool suspended;
        private int powerGeneration;
        public SignInService() : this(AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\'), 60000) { }
        internal SignInService(string root, int standbyLeaseMilliseconds)
        {
            if (standbyLeaseMilliseconds <= 0) throw new ArgumentOutOfRangeException("standbyLeaseMilliseconds");
            this.root = root; this.standbyLeaseMilliseconds = standbyLeaseMilliseconds;
            ServiceName = "VisoSignIn"; CanShutdown = true; CanHandlePowerEvent = true; CanHandleSessionChangeEvent = true;
            standbyExpiry = new Timer(delegate { RetireStandby(); }, null, Timeout.Infinite, Timeout.Infinite);
        }
        protected override void OnStart(string[] args)
        {
            if (!WindowsIdentity.GetCurrent().IsSystem || !root.Equals(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Viso"), StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Install Viso sign-in into Program Files and run it through Windows Services.");
            for (int i = 0; i < 8; i++) Task.Run((Func<Task>)Listen);
            ObserveFailure(Task.Run((Action)PrepareBootWorker));
        }
        protected override void OnStop()
        {
            lock (connections) {
                if (stopping) return;
                stopping = suspended = true; Interlocked.Increment(ref powerGeneration);
                foreach (var pipe in connections) pipe.Dispose();
            }
            lock (workers) {
                standbyExpiry.Dispose();
                foreach (var worker in workers) worker.Dispose();
                workers.Clear(); standby = null; standbyDeadline = 0;
            }
        }
        protected override void Dispose(bool disposing) { if (disposing) OnStop(); base.Dispose(disposing); }
        protected override void OnShutdown() { OnStop(); }
        protected override bool OnPowerEvent(PowerBroadcastStatus status) { PowerChanged(status); return true; }
        internal void PowerChanged(PowerBroadcastStatus status)
        {
            if (stopping) return;
            if (status == PowerBroadcastStatus.Suspend) {
                lock (connections) {
                    if (stopping) return;
                    suspended = true; Interlocked.Increment(ref powerGeneration);
                    // Listening pipes are recreated by Listen; connected pipes
                    // must not deliver a result belonging to the previous wake.
                    foreach (var pipe in connections) pipe.Dispose();
                }
                lock (workers) {
                    if (stopping) return;
                    standbyExpiry.Change(Timeout.Infinite, Timeout.Infinite);
                    foreach (var worker in workers) worker.Dispose();
                    workers.Clear(); standby = null; standbyDeadline = 0;
                }
            } else if (status == PowerBroadcastStatus.ResumeAutomatic || status == PowerBroadcastStatus.ResumeSuspend || status == PowerBroadcastStatus.ResumeCritical) {
                suspended = false;
                // Automatic background wake does not imply a user is present.
                if (status != PowerBroadcastStatus.ResumeAutomatic && !stopping) ObserveFailure(Task.Run((Action)PrepareWorker));
            }
        }
        protected override void OnSessionChange(SessionChangeDescription change)
        {
            if (change.Reason == SessionChangeReason.SessionLock && !stopping && !suspended) ObserveFailure(Task.Run((Action)PrepareWorker));
        }
        private void RetireStandby()
        {
            lock (workers) {
                if (standby == null) return;
                // A callback queued for a consumed/retired worker may run after
                // a replacement has been prepared. Respect the new lease.
                long remaining = standbyDeadline - Stopwatch.GetTimestamp();
                if (remaining > 0) {
                    standbyExpiry.Change((int)Math.Max(1, Math.Ceiling(remaining * 1000.0 / Stopwatch.Frequency)), Timeout.Infinite);
                    return;
                }
                var worker = standby; standby = null;
                standbyDeadline = 0; workers.Remove(worker); worker.Dispose();
            }
        }
        internal void RequirePowerGeneration(int generation)
        {
            if (stopping || suspended || generation != Volatile.Read(ref powerGeneration))
                throw new OperationCanceledException("Power state changed. Start a new sign-in attempt.");
        }
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
            int generation = Volatile.Read(ref powerGeneration);
            string[] request = null; string failure = null;
            try {
                request = await Wire.Receive(pipe).ConfigureAwait(false);
                RequirePowerGeneration(generation);
                var caller = Native.Identify(pipe);
                if (request[0] == "verify") {
                    caller.RequireLogonUI();
                    if (request.Length != 4) throw new InvalidDataException();
                    if (!await camera.WaitAsync(0).ConfigureAwait(false)) throw new InvalidOperationException("The camera is already being used by another sign-in attempt.");
                    try { await Verify(pipe, request, generation).ConfigureAwait(false); } finally { camera.Release(); }
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
                        }, generation).ConfigureAwait(false);
                        await vault.Gate.WaitAsync().ConfigureAwait(false);
                        try { RequirePowerGeneration(generation); vault.SaveIfCurrent(account, version); }
                        finally { vault.Gate.Release(); }
                    } finally { account.Forget(); }
                    await Wire.Send(pipe, "ok", "Linked: " + qualified).ConfigureAwait(false);
                } else throw new InvalidDataException("Unknown sign-in request.");
            } catch (Exception error) {
                failure = error is InvalidOperationException || error is ArgumentException || error is UnauthorizedAccessException ? error.Message : "Windows face sign-in could not complete. Use another sign-in option and check Viso Settings.";
            } finally { if (request != null) Array.Clear(request, 0, request.Length); }
            if (failure != null) { try { await Wire.Send(pipe, "error", failure).ConfigureAwait(false); } catch { } }
        }
        private async Task WithWorker(Account account, string command, Func<Worker, Task> action, int generation)
        {
            Worker worker;
            lock (workers) {
                RequirePowerGeneration(generation);
                worker = command == "verify" ? standby : null;
                if (command == "verify") { standby = null; standbyDeadline = 0; standbyExpiry.Change(Timeout.Infinite, Timeout.Infinite); }
                if (worker != null && (!worker.IsAlive || worker.Ready.IsFaulted)) { workers.Remove(worker); worker.Dispose(); worker = null; }
                if (worker == null) { worker = new Worker(root, command == "verify"); workers.Add(worker); }
            }
            try {
                // Begin the disconnect watcher before a potentially cold model
                // load. Writing a profile must also be inside the deadline: a
                // prewarming child may not yet be draining stdin.
                var task = action(worker);
                var start = Task.Run(delegate { RequirePowerGeneration(generation); worker.Start(account, command); });
                await CompleteWorker(start, task, command == "verify" ? 45000 : 20000).ConfigureAwait(false);
            } finally {
                lock (workers) { if (workers.Remove(worker)) worker.Dispose(); }
                if (command == "verify" && !stopping && !suspended && generation == Volatile.Read(ref powerGeneration)) ObserveFailure(Task.Run((Action)PrepareWorker));
            }
        }
        internal static async Task CompleteWorker(Task start, Task action, int milliseconds)
        {
            ObserveFailure(start); ObserveFailure(action);
            using (var deadline = new CancellationTokenSource()) {
                try {
                    var timeout = Task.Delay(milliseconds, deadline.Token);
                    var first = await Task.WhenAny(start, action, timeout).ConfigureAwait(false);
                    // Surface disconnect/write failure immediately, even if its
                    // sibling is stuck. Closing the Job then releases both pipes.
                    if (first == action) await action.ConfigureAwait(false);
                    if (first == start) await start.ConfigureAwait(false);
                    var complete = Task.WhenAll(start, action); ObserveFailure(complete);
                    if (await Task.WhenAny(complete, timeout).ConfigureAwait(false) != complete) throw new System.TimeoutException("Recognition timed out.");
                    await complete.ConfigureAwait(false);
                } finally { deadline.Cancel(); }
            }
        }
        private void PrepareWorker()
        {
            PrepareWorkerFor(standbyLeaseMilliseconds);
        }
        private void PrepareBootWorker()
        {
            // First logon can follow device startup/updates or a user pausing at
            // the lock screen. Keep that model-only cache for five minutes, not
            // indefinitely; later locks/retries retain the ordinary short lease.
            PrepareWorkerFor(BootStandbyLeaseMilliseconds);
        }
        private void PrepareWorkerFor(int leaseMilliseconds)
        {
            // One unused, model-only process. Every verification consumes and
            // destroys it, so profiles, calibration and frames never cross attempts.
            // Warmup does not acquire the camera or read the account vault.
            try {
                lock (workers) {
                    // Startup, tile selection and session notifications can race.
                    // A consumed standby is still an active worker: do not launch
                    // a second model load beside it and slow the requested scan.
                    if (stopping || suspended || workers.Count != 0) return;
                    standby = new Worker(root, true); workers.Add(standby);
                    var prepared = standby;
                    // An unused model process is a latency cache, not permanent
                    // residency. Never retain a failed initialization until login.
                    standbyDeadline = Stopwatch.GetTimestamp() + (long)(Stopwatch.Frequency * (leaseMilliseconds / 1000.0));
                    standbyExpiry.Change(leaseMilliseconds, Timeout.Infinite);
                    prepared.Ready.ContinueWith(delegate(Task ready) {
                        var ignored = ready.Exception;
                        lock (workers) {
                            if (standby != prepared) return;
                            standby = null; standbyDeadline = 0; standbyExpiry.Change(Timeout.Infinite, Timeout.Infinite);
                            workers.Remove(prepared); prepared.Dispose();
                        }
                    }, TaskContinuationOptions.OnlyOnFaulted);
                }
            } catch { /* A later explicit scan retries worker creation. */ }
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
        private async Task Verify(NamedPipeServerStream pipe, string[] request, int generation)
        {
            RequirePowerGeneration(generation);
            Account account;
            await vault.Gate.WaitAsync().ConfigureAwait(false);
            try { account = vault.Load(request[1]); } finally { vault.Gate.Release(); }
            try {
                if (!Matches(account, request[1], request[2], request[3])) throw new InvalidOperationException("Open Viso Settings in this Windows account and link Windows sign-in first.");
                await WithWorker(account, "verify", worker => Relay(pipe, worker.Next, worker.Ack), generation).ConfigureAwait(false);
                RequirePowerGeneration(generation);
                // Re-read after recognition so unlink/relink revokes in-flight attempts.
                await vault.Gate.WaitAsync().ConfigureAwait(false);
                try {
                    RequirePowerGeneration(generation);
                    if (!vault.IsCurrent(account)) throw new UnauthorizedAccessException("Account link changed. Start a new sign-in attempt.");
                    await Wire.Send(pipe, "credential", account.Kind, account.Qualified, account.Password).ConfigureAwait(false);
                } finally { vault.Gate.Release(); }
            } finally { if (account != null) account.Forget(); }
        }
        public static void Main() { ServiceBase.Run(new SignInService()); }
    }
}
