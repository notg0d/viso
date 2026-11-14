using System;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Security.Principal;
using System.Text;
using System.Threading.Tasks;
using System.Diagnostics;
using System.Web.Script.Serialization;
using System.Collections.Generic;
using System.Reflection;
using System.ServiceProcess;

namespace Viso.SignIn
{
    internal static class Tests
    {
        private static int checks;
        private static void Check(bool result) { checks++; if (!result) throw new Exception("Check " + checks + " failed."); }
        private static void Reject(Action action) { try { action(); } catch { checks++; return; } throw new Exception("Expected rejection."); }
        private static T Field<T>(SignInService service, string name) { return (T)typeof(SignInService).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(service); }
        private static void Invoke(SignInService service, string name) { typeof(SignInService).GetMethod(name, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(service, null); }
        public static int Main(string[] args)
        {
            try {
                var test = args.Length == 2 && args[0] == "--runtime" ? TestRuntime(args[1]) : Run();
                if (!test.Wait(TimeSpan.FromSeconds(args.Length == 2 && args[0] == "--runtime" ? 120 : 45))) throw new Exception("Service tests timed out.");
                test.GetAwaiter().GetResult(); Console.WriteLine("Service checks passed: " + checks + "."); return 0;
            }
            catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        }
        private static async Task Run()
        {
            Console.WriteLine("Checking sign-in protocol and account rules...");
            string[] fields = {"link", "microsoft", "Zoë 李@example.com", "fake\npassword", "{}", "0"};
            var encoded = Wire.Encode(fields); Check(Wire.Decode(encoded).SequenceEqual(fields));
            using (var stream = new MemoryStream()) { await Wire.Send(stream, fields); stream.Position = 0; Check((await Wire.Receive(stream)).SequenceEqual(fields)); }
            Reject(delegate { Wire.Decode(encoded.Take(encoded.Length - 1).ToArray()); });
            Reject(delegate { Wire.Decode(encoded.Concat(new byte[] {0}).ToArray()); });
            Reject(delegate { Wire.Decode(Wire.Encode("embedded\0null")); });
            Reject(delegate { Wire.Encode(new string('a', Wire.Limit)); });
            Reject(delegate { Wire.Encode(new string[0]); });
            Reject(delegate { Wire.Decode(new byte[] { 1,0,0,0, 1,0,0,0, 1,0,0,0, 255 }); });
            var bad = (byte[])encoded.Clone(); bad[0] = 2; Reject(delegate { Wire.Decode(bad); });
            Check(Native.AccountName("local", ".\\tester") == Environment.MachineName + "\\tester");
            Check(Native.AccountName("microsoft", "person@example.com") == "MicrosoftAccount\\person@example.com");
            Reject(delegate { Native.AccountName("local", "OTHERPC\\user"); });
            Reject(delegate { Native.AccountName("microsoft", "AzureAD\\person@example.com"); });
            Reject(delegate { Native.AccountName("microsoft", "user"); });
            Reject(delegate { Native.AccountName("work", "user"); });
            Check(SignInService.ParseExposureAssist("true") && !SignInService.ParseExposureAssist("false"));
            foreach (string option in new[] { "1", "True", "", null }) Reject(delegate { SignInService.ParseExposureAssist(option); });
            var caller = new Native.Caller { Sid = "S-1-5-18", System = true, Session = 1, Image = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "LogonUI.exe") };
            caller.RequireLogonUI(); Check(true);
            caller.System = false; Reject(caller.RequireLogonUI); caller.System = true;
            caller.Session = 0; Reject(caller.RequireLogonUI); caller.Session = 1;
            caller.Image = @"C:\Temp\LogonUI.exe"; Reject(caller.RequireLogonUI);
            string directory = Path.Combine(Path.GetTempPath(), "Viso-signin-tests-" + Guid.NewGuid().ToString("N"));
            Console.WriteLine("Checking encrypted account storage...");
            Directory.CreateDirectory(directory);
            try {
                var vault = new Vault(directory);
                string sid = WindowsIdentity.GetCurrent().User.Value;
                var account = new Account { Sid = sid, Kind = "microsoft", Qualified = "MicrosoftAccount\\fake@example.com", Password = "Fake credential 42", Profile = "{}", Revision = "one", Camera = 0 };
                vault.Save(account); var loaded = vault.Load(sid);
                Check(loaded.Password == account.Password && loaded.Qualified == account.Qualified);
                // Serialize a real pre-0.8.3 record with no assistance field.
                var legacy = new { account.Sid, account.Kind, account.Qualified, account.Password, account.Profile, account.Revision, account.Camera };
                byte[] clear = Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(legacy));
                try { File.WriteAllBytes(Path.Combine(directory, sid + ".dpapi"), System.Security.Cryptography.ProtectedData.Protect(clear, null, System.Security.Cryptography.DataProtectionScope.LocalMachine)); }
                finally { Array.Clear(clear, 0, clear.Length); }
                loaded = vault.Load(sid);
                Check(!loaded.ExposureAssist); // Old account records default to off.
                long previousSettings = vault.Version(sid);
                vault.SetCameraSettings(sid, 2, true);
                var tuned = vault.Load(sid);
                Check(tuned.Camera == 2 && tuned.ExposureAssist && tuned.Password == account.Password && tuned.Profile == account.Profile);
                Check(tuned.Revision != loaded.Revision && !vault.IsCurrent(loaded));
                Reject(delegate { vault.SaveIfCurrent(account, previousSettings); });
                Reject(delegate { vault.SetCameraSettings(sid, 33, true); });
                vault.SetCameraSettings(sid, 0, false);
                loaded = vault.Load(sid);
                Check(!loaded.ExposureAssist && loaded.Camera == 0);
                Check(!Encoding.UTF8.GetString(File.ReadAllBytes(Directory.GetFiles(directory).Single())).Contains(account.Password));
                Check(SignInService.Matches(loaded, sid, "microsoft", "MicrosoftAccount\\FAKE@example.com"));
                Check(!SignInService.Matches(loaded, "S-1-5-21-1-2-3-1001", "microsoft", account.Qualified));
                Check(!SignInService.Matches(loaded, sid, "local", account.Qualified));
                Check(!SignInService.Matches(loaded, sid, "microsoft", "MicrosoftAccount\\other@example.com"));
                long version = vault.Version(sid);
                Check(vault.IsCurrent(loaded));
                account.Revision = "two"; vault.SaveIfCurrent(account, version); Check(!vault.IsCurrent(loaded));
                Reject(delegate { vault.SaveIfCurrent(account, version); });
                Reject(delegate { vault.Load("..\\another-account"); });
                version = vault.Version(sid);
                vault.Delete(sid); Check(vault.Load(sid) == null && !vault.IsCurrent(account));
                Reject(delegate { vault.SaveIfCurrent(account, version); });
                version = vault.Version(sid); vault.Delete(sid);
                Reject(delegate { vault.SaveIfCurrent(account, version); });
                vault.SaveIfCurrent(account, vault.Version(sid)); Check(vault.IsCurrent(account));
                // DPAPI alone does not bind a record to its filename/SID.
                string other = "S-1-5-21-1-2-3-1001";
                File.Copy(Path.Combine(directory, sid + ".dpapi"), Path.Combine(directory, other + ".dpapi"));
                Reject(delegate { vault.Load(other); });
            } finally { Directory.Delete(directory, true); }
            // Real OS pipe impersonation binds to this process's SID; a lookalike server
            // cannot pass the SCM service-PID check, even with the same wire protocol.
            string pipeName = "Viso-Test-" + Guid.NewGuid().ToString("N");
            Console.WriteLine("Checking Windows pipe peer identity...");
            using (var server = new NamedPipeServerStream(pipeName, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous, 4096, 4096, SignInService.PipePermissions()))
            using (var client = new NamedPipeClientStream(".", pipeName, PipeAccessRights.ReadWrite, PipeOptions.Asynchronous, TokenImpersonationLevel.Impersonation, HandleInheritability.None)) {
                var waiting = server.WaitForConnectionAsync(); await client.ConnectAsync(2000); await waiting;
                Reject(delegate { Native.TrustServer(client); });
                var reading = Wire.Receive(server);
                await Wire.Send(client, "status");
                await reading;
                var peer = Native.Identify(server); Check(peer.Sid == WindowsIdentity.GetCurrent().User.Value); Reject(peer.RequireLogonUI);
            }
            Console.WriteLine("Checking sign-in prompt acknowledgment and disconnect cancellation...");
            await TestRelay(false); await TestRelay(true);
            var never = new TaskCompletionSource<int>();
            var timed = SignInService.CompleteWorker(never.Task, never.Task, 20);
            Check(await Task.WhenAny(timed, Task.Delay(2000)) == timed);
            Check(timed.IsFaulted && timed.Exception.InnerException is System.TimeoutException);
            var failedWrite = new TaskCompletionSource<int>(); failedWrite.SetException(new IOException("Canceled writer"));
            var failed = SignInService.CompleteWorker(failedWrite.Task, never.Task, 10000);
            Check(await Task.WhenAny(failed, Task.Delay(2000)) == failed);
            Reject(delegate { failed.GetAwaiter().GetResult(); });
            var success = SignInService.CompleteWorker(Task.FromResult(0), Task.FromResult(0), 10000);
            await success; Check(success.IsCompleted && !success.IsFaulted);
            Console.WriteLine("Checking model readiness validation and initialization deadline...");
            await Worker.AwaitInitialization(Task.FromResult(new Dictionary<string, object> { { "event", "ready" } }), 1000); Check(true);
            Reject(delegate { Worker.AwaitInitialization(Task.FromResult(new Dictionary<string, object> { { "event", "accepted" } }), 1000).GetAwaiter().GetResult(); });
            var silent = new TaskCompletionSource<Dictionary<string, object>>();
            var initialization = Worker.AwaitInitialization(silent.Task, 20);
            Check(await Task.WhenAny(initialization, Task.Delay(2000)) == initialization);
            Check(initialization.IsFaulted && initialization.Exception.InnerException is System.TimeoutException);
            Console.WriteLine("Checking suspend revocation and idempotent service disposal...");
            using (var service = new SignInService()) {
                Check(service.CanHandlePowerEvent && service.CanHandleSessionChangeEvent);
                int generation = Field<int>(service, "powerGeneration"); service.RequirePowerGeneration(generation);
                string name = "Viso-Test-" + Guid.NewGuid().ToString("N");
                using (var pipe = new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous)) {
                    Field<HashSet<NamedPipeServerStream>>(service, "connections").Add(pipe);
                    var waiting = pipe.WaitForConnectionAsync();
                    service.PowerChanged(PowerBroadcastStatus.Suspend);
                    Check(Field<bool>(service, "suspended"));
                    Check(await Task.WhenAny(waiting, Task.Delay(2000)) == waiting);
                    Reject(delegate { waiting.GetAwaiter().GetResult(); });
                    Reject(delegate { service.RequirePowerGeneration(generation); });
                    service.PowerChanged(PowerBroadcastStatus.ResumeAutomatic);
                    Check(!Field<bool>(service, "suspended") && Field<Worker>(service, "standby") == null);
                    Reject(delegate { service.RequirePowerGeneration(generation); });
                    var staleWorker = (Task)typeof(SignInService).GetMethod("WithWorker", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(service, new object[] {
                        new Account { Profile = "{}" }, "verify", new Func<Worker, Task>(delegate { throw new Exception("Stale request acquired a worker."); }), generation, -1, 0
                    });
                    Reject(delegate { staleWorker.GetAwaiter().GetResult(); });
                    Check(Field<HashSet<Worker>>(service, "workers").Count == 0);
                    service.RequirePowerGeneration(Field<int>(service, "powerGeneration"));
                    service.Dispose(); service.Dispose();
                    service.PowerChanged(PowerBroadcastStatus.Suspend); service.PowerChanged(PowerBroadcastStatus.ResumeSuspend);
                    Check(Field<bool>(service, "stopping") && Field<Worker>(service, "standby") == null);
                    Reject(delegate { service.RequirePowerGeneration(Field<int>(service, "powerGeneration")); });
                }
            }
            Console.WriteLine("Checking stale session-state queries and session revocation...");
            using (var entered = new System.Threading.ManualResetEventSlim())
            using (var release = new System.Threading.ManualResetEventSlim())
            using (var service = new SignInService("unused", delegate(int session, bool? awaiting) {
                if (awaiting == true) { entered.Set(); if (!release.Wait(2000)) throw new Exception("Blocked state query timed out."); }
                return awaiting == true;
            })) {
                typeof(SignInService).GetField("standbyWanted", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(service, true);
                var oldLock = service.SessionChanged(SessionChangeReason.SessionLock, 1);
                Check(entered.Wait(2000));
                Check(!Field<bool>(service, "standbyWanted")); // Do not replace workers from stale state while the query is pending.
                int generation = service.SessionGeneration(1);
                await service.SessionChanged(SessionChangeReason.SessionUnlock, 1);
                release.Set(); await oldLock;
                Check(!Field<bool>(service, "standbyWanted") && Field<Worker>(service, "standby") == null);
                Reject(delegate { service.RequireSessionGeneration(1, generation); });
                service.RequireSessionGeneration(2, 0); Check(true);
            }
            // PIN/password sign-in revokes only that session's result transport,
            // including the interval after its camera worker has already exited.
            using (var service = new SignInService("unused", delegate { return false; }))
            using (var first = new NamedPipeServerStream("Viso-Test-" + Guid.NewGuid().ToString("N"), PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous))
            using (var other = new NamedPipeServerStream("Viso-Test-" + Guid.NewGuid().ToString("N"), PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous)) {
                Field<Dictionary<NamedPipeServerStream, int>>(service, "verifyingSessions").Add(first, 1);
                Field<Dictionary<NamedPipeServerStream, int>>(service, "verifyingSessions").Add(other, 2);
                var waiting = first.WaitForConnectionAsync();
                var otherWaiting = other.WaitForConnectionAsync();
                await service.SessionChanged(SessionChangeReason.SessionUnlock, 1);
                Check(await Task.WhenAny(waiting, Task.Delay(2000)) == waiting);
                Reject(delegate { waiting.GetAwaiter().GetResult(); });
                Check(!otherWaiting.IsCompleted);
                other.Dispose(); SignInService.ObserveFailure(otherWaiting);
            }
            Console.WriteLine("Checking console and multi-session model retention...");
            var sessions = new[] { new SessionState.Session { Id = 0, State = 0 }, new SessionState.Session { Id = 1, State = 0 }, new SessionState.Session { Id = 2, State = 4 } };
            Check(!SessionState.NeedsModels(1, sessions, -1, null, id => id == 2)); // Disconnected user is ignored.
            Check(SessionState.NeedsModels(1, sessions, 1, true, id => false)); // Lock notification wins over a lagging query.
            Check(!SessionState.NeedsModels(1, sessions, 1, false, id => true)); // Unlock notification wins too.
            sessions[2].State = 1;
            Check(SessionState.NeedsModels(1, sessions, 1, false, id => id == 2)); // Another connected locked user.
            Check(!SessionState.NeedsModels(1, sessions, 2, false, id => false));
            Check(SessionState.NeedsModels(uint.MaxValue, new SessionState.Session[0], -1, null, id => false)); // Console transition.
            Check(SessionState.NeedsModels(1, sessions, -1, null, id => true)); // Locked or unknown state.
            // The real WTS query inspects state only. It does not open a camera,
            // access the account vault, or trigger workstation lock/unlock.
            bool stateNeedsModels = SessionState.NeedsModels(-1, null);
            Console.WriteLine("Current Windows state needs model standby: " + stateNeedsModels + ".");
            Check(true);
        }
        private static async Task TestRelay(bool disconnect)
        {
            string name = "Viso-Test-" + Guid.NewGuid().ToString("N");
            using (var server = new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous))
            using (var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous)) {
                var connected = server.WaitForConnectionAsync(); await client.ConnectAsync(2000); await connected;
                if (disconnect) {
                    var blockedInference = new TaskCompletionSource<Dictionary<string, object>>();
                    var relay = SignInService.Relay(server, () => blockedInference.Task, delegate { throw new Exception("Unexpected acknowledgment."); });
                    var blockedWrite = new TaskCompletionSource<int>();
                    var completion = SignInService.CompleteWorker(blockedWrite.Task, relay, 10000);
                    client.Dispose();
                    Check(await Task.WhenAny(completion, Task.Delay(2000)) == completion);
                    Reject(delegate { completion.GetAwaiter().GetResult(); });
                } else {
                    int step = 0, acknowledgments = 0;
                    var relay = SignInService.Relay(server, delegate {
                        string kind = new[] { "status", "prompt", "accepted" }[step++];
                        if (kind == "accepted") Check(acknowledgments == 1);
                        return Task.FromResult(new Dictionary<string, object> { { "event", kind }, { "message", kind } });
                    }, delegate { acknowledgments++; });
                    Check((await Wire.Receive(client))[0] == "status");
                    var prompt = Wire.Receive(client); await Wire.Send(client, "ack");
                    Check((await prompt)[0] == "prompt" && acknowledgments == 0);
                    await Wire.Send(client, "ack"); await relay;
                    Check(step == 3 && acknowledgments == 1);
                }
            }
        }
        private static async Task TestRuntime(string root)
        {
            Console.WriteLine("Checking packaged service-to-Python validation and job cleanup...");
            var vector = new double[128]; vector[0] = 1;
            var profile = new { id = "fake-test-profile", model_id = "sface-2021dec-yunet-2023mar-v1", source = "camera", guided = true, samples = 5, embedding = vector, templates = Enumerable.Repeat(vector, 5).ToArray() };
            var account = new Account { Profile = new JavaScriptSerializer().Serialize(profile), Camera = 0 };
            using (var worker = new Worker(root)) {
                worker.Start(account, "validate");
                Check(Convert.ToString((await worker.Next())["event"]) == "validated");
            }
            using (var worker = new Worker(root, true)) {
                // Model warmup completes without a profile or a camera request.
                var noticeTimer = Stopwatch.StartNew();
                var notice = await worker.Next();
                Check(Convert.ToString(notice["event"]) == "status" && Convert.ToString(notice["message"]).Contains("camera is off"));
                Check(noticeTimer.ElapsedMilliseconds < 1000 && !worker.Ready.IsCompleted);
                Console.WriteLine("Cold initialization status: " + noticeTimer.ElapsedMilliseconds + " ms.");
                await worker.Ready;
                Check(worker.IsAlive);
                Console.WriteLine("Cold model preparation: " + worker.StartupMilliseconds + " ms (no camera).");
                var warmRequest = Stopwatch.StartNew();
                worker.Start(account, "validate");
                Check(Convert.ToString((await worker.Next())["event"]) == "validated");
                Console.WriteLine("Warm worker validation request: " + warmRequest.ElapsedMilliseconds + " ms (no camera).");
                using (var process = Process.GetProcessById(worker.ProcessId)) Check(process.WaitForExit(3000));
            }
            account.Profile = "{}";
            using (var worker = new Worker(root)) {
                worker.Start(account, "validate");
                Check(Convert.ToString((await worker.Next())["event"]) == "error");
            }
            var waiting = new Worker(root, true);
            using (var process = Process.GetProcessById(waiting.ProcessId)) {
                waiting.Dispose(); waiting.Dispose();
                Check(process.WaitForExit(3000));
            }
            // Realistic normalized floats keep the 17-view payload under both
            // the link request's 64 KiB cap and the encrypted vault/wire limits.
            var realistic = Enumerable.Range(0, 128).Select(i => Math.Sin(i + .37)).ToArray();
            double norm = Math.Sqrt(realistic.Sum(x => x * x)); realistic = realistic.Select(x => x / norm).ToArray();
            var groups = new[] { "center", "left", "up_left", "up", "up_right", "right", "down_right", "down", "down_left", "left", "up_left", "up", "up_right", "right", "down_right", "down", "down_left" };
            var poses = groups.Select(step => new { step = step, yaw = 0.0, pitch = 0.0, observations = 3 }).ToArray();
            account.Profile = new JavaScriptSerializer().Serialize(new { id = "fake-circle", model_id = "sface-2021dec-yunet-2023mar-v1", source = "camera", guided = true, enrollment_version = "circular-v1", samples = 17, observations = 51, embedding = realistic, templates = Enumerable.Repeat(realistic, 17).ToArray(), template_groups = groups, poses = poses });
            Check(account.Profile.Length < 65536);
            Console.WriteLine("Circular profile payload: " + account.Profile.Length + " characters.");
            using (var worker = new Worker(root)) {
                worker.Start(account, "validate"); Check(Convert.ToString((await worker.Next())["event"]) == "validated");
            }
            account.Profile = account.Profile.Replace("\"observations\":51", "\"observations\":50");
            using (var worker = new Worker(root)) {
                worker.Start(account, "validate"); Check(Convert.ToString((await worker.Next())["event"]) == "error");
            }
            Console.WriteLine("Checking Windows-state retention, alternative sign-in and suspend cleanup...");
            bool wanted = true;
            using (var service = new SignInService(root, delegate { return wanted; })) {
                await service.RefreshSessionState(); var prepared = Field<Worker>(service, "standby"); Check(prepared != null);
                await prepared.Ready;
                await service.SessionChanged(SessionChangeReason.SessionLock, 1);
                await service.RefreshSessionState();
                Check(Field<Worker>(service, "standby") == prepared && prepared.IsAlive && Field<HashSet<Worker>>(service, "workers").Count == 1);
                Check(typeof(SignInService).GetField("standbyExpiry", BindingFlags.Instance | BindingFlags.NonPublic) == null);
                using (var process = Process.GetProcessById(prepared.ProcessId)) {
                    Console.WriteLine("Model-only standby: " + process.PrivateMemorySize64 + " private bytes; retained while sign-in is needed.");
                    wanted = false; await service.SessionChanged(SessionChangeReason.SessionUnlock, 1);
                    Check(process.WaitForExit(3000) && Field<Worker>(service, "standby") == null);
                }
                Invoke(service, "PrepareWorker"); Check(Field<Worker>(service, "standby") == null);
                wanted = true; await service.SessionChanged(SessionChangeReason.SessionLogoff, 1);
                prepared = Field<Worker>(service, "standby"); await prepared.Ready;
                using (var process = Process.GetProcessById(prepared.ProcessId)) {
                    service.PowerChanged(PowerBroadcastStatus.Suspend); Check(process.WaitForExit(3000));
                    Check(Field<Worker>(service, "standby") == null && Field<HashSet<Worker>>(service, "workers").Count == 0);
                }
                service.PowerChanged(PowerBroadcastStatus.ResumeAutomatic); Check(Field<Worker>(service, "standby") == null);
                service.PowerChanged(PowerBroadcastStatus.ResumeSuspend);
                await WaitForStandby(service); prepared = Field<Worker>(service, "standby"); await prepared.Ready;
                // An unlock of another user must retain the cache if a connected
                // locked session still needs sign-in (the WTS resolver says true).
                await service.SessionChanged(SessionChangeReason.SessionUnlock, 2);
                Check(Field<Worker>(service, "standby") == prepared && prepared.IsAlive);
                using (var process = Process.GetProcessById(prepared.ProcessId)) {
                    service.Dispose(); service.Dispose(); Check(process.WaitForExit(3000));
                    await service.RefreshSessionState(); Check(Field<Worker>(service, "standby") == null);
                }
            }
            wanted = true;
            using (var service = new SignInService(root, delegate { return wanted; })) {
                await service.RefreshSessionState(); var prepared = Field<Worker>(service, "standby"); await prepared.Ready;
                using (var process = Process.GetProcessById(prepared.ProcessId)) {
                    // Invalid profile is rejected before the verify command can
                    // request a camera, while exercising actual standby consumption.
                    var consumed = (Task)typeof(SignInService).GetMethod("WithWorker", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(service, new object[] {
                        new Account { Profile = "{}" }, "verify", new Func<Worker, Task>(async delegate(Worker worker) {
                            // Reproduce boot/session warmup arriving after a scan
                            // consumes the cache. Never load a competing standby.
                            Invoke(service, "PrepareWorker"); await service.RefreshSessionState();
                            Check(Field<Worker>(service, "standby") == null && Field<HashSet<Worker>>(service, "workers").Count == 1);
                            Check(worker == prepared && Convert.ToString((await worker.Next())["event"]) == "error");
                        }), Field<int>(service, "powerGeneration"), 1, service.SessionGeneration(1)
                    });
                    await consumed; Check(process.WaitForExit(3000));
                    await WaitForStandby(service);
                    var replacement = Field<Worker>(service, "standby");
                    Check(replacement != null && replacement != prepared && Field<HashSet<Worker>>(service, "workers").Count == 1);
                    await replacement.Ready;
                }
                prepared = Field<Worker>(service, "standby");
                using (var process = Process.GetProcessById(prepared.ProcessId)) {
                    int previousGeneration = service.SessionGeneration(1);
                    var canceled = (Task)typeof(SignInService).GetMethod("WithWorker", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(service, new object[] {
                        new Account { Profile = "{}" }, "verify", new Func<Worker, Task>(async delegate(Worker worker) {
                            wanted = false;
                            await service.SessionChanged(SessionChangeReason.SessionUnlock, 1);
                            Reject(delegate { service.RequireSessionGeneration(1, previousGeneration); });
                            await worker.Next();
                        }), Field<int>(service, "powerGeneration"), 1, previousGeneration
                    });
                    try { await canceled; throw new Exception("Session unlock did not cancel the worker."); }
                    catch (OperationCanceledException) { Check(true); }
                    catch (IOException) { Check(true); }
                    catch (InvalidOperationException) { Check(true); }
                    Check(process.WaitForExit(3000));
                    Invoke(service, "PrepareWorker"); Check(Field<Worker>(service, "standby") == null);
                }
            }
            // A deliberately failing worker uses a separate temporary payload;
            // it cannot touch the packaged models, camera or account vault.
            string failedRoot = Path.Combine(Path.GetTempPath(), "Viso-failed-worker-" + Guid.NewGuid().ToString("N"));
            try {
                Directory.CreateDirectory(Path.Combine(failedRoot, "runtime"));
                Directory.CreateDirectory(Path.Combine(failedRoot, "backend", "viso"));
                foreach (string file in Directory.GetFiles(Path.Combine(root, "runtime"))) File.Copy(file, Path.Combine(failedRoot, "runtime", Path.GetFileName(file)));
                File.WriteAllText(Path.Combine(failedRoot, "backend", "viso", "signin.py"), "print('{\"event\":\"error\",\"message\":\"synthetic initialization failure\"}', flush=True)\n");
                using (var service = new SignInService(failedRoot, delegate { return true; })) {
                    await service.RefreshSessionState(); var prepared = Field<Worker>(service, "standby"); Check(prepared != null);
                    try { await prepared.Ready; throw new Exception("Expected failed warmup."); } catch (IOException) { Check(true); }
                    var deadline = Stopwatch.StartNew();
                    while (Field<Worker>(service, "standby") != null && deadline.ElapsedMilliseconds < 2000) await Task.Delay(10);
                    Check(Field<Worker>(service, "standby") == null && Field<HashSet<Worker>>(service, "workers").Count == 0 && !prepared.IsAlive);
                }
            } finally { Directory.Delete(failedRoot, true); }
        }
        private static async Task WaitForStandby(SignInService service)
        {
            var deadline = Stopwatch.StartNew();
            while (Field<Worker>(service, "standby") == null && deadline.ElapsedMilliseconds < 3000) await Task.Delay(10);
            Check(Field<Worker>(service, "standby") != null);
        }
    }
}
