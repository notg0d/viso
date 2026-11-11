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
                if (!test.Wait(TimeSpan.FromSeconds(45))) throw new Exception("Service tests timed out.");
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
                        new Account { Profile = "{}" }, "verify", new Func<Worker, Task>(delegate { throw new Exception("Stale request acquired a worker."); }), generation
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
                await worker.Ready;
                Check(worker.IsAlive);
                worker.Start(account, "validate");
                Check(Convert.ToString((await worker.Next())["event"]) == "validated");
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
            Console.WriteLine("Checking standby leases, stale timer callbacks and suspend job cleanup...");
            using (var service = new SignInService(root, 60000)) {
                Invoke(service, "PrepareWorker"); var prepared = Field<Worker>(service, "standby"); Check(prepared != null);
                await prepared.Ready;
                using (var process = Process.GetProcessById(prepared.ProcessId)) {
                    Console.WriteLine("Model-only standby footprint: " + process.PrivateMemorySize64 + " private bytes; " + process.WorkingSet64 + " working-set bytes. Unused residency is now leased, not permanent.");
                }
                Invoke(service, "RetireStandby"); // Simulates an old queued callback before the new lease expires.
                Check(Field<Worker>(service, "standby") == prepared && prepared.IsAlive);
                typeof(SignInService).GetField("standbyDeadline", BindingFlags.Instance | BindingFlags.NonPublic).SetValue(service, Stopwatch.GetTimestamp() - 1);
                using (var process = Process.GetProcessById(prepared.ProcessId)) {
                    Invoke(service, "RetireStandby"); Check(process.WaitForExit(3000));
                    Check(Field<Worker>(service, "standby") == null && Field<HashSet<Worker>>(service, "workers").Count == 0);
                }
                Invoke(service, "PrepareWorker"); prepared = Field<Worker>(service, "standby"); await prepared.Ready;
                using (var process = Process.GetProcessById(prepared.ProcessId)) {
                    service.PowerChanged(PowerBroadcastStatus.Suspend); Check(process.WaitForExit(3000));
                    Check(Field<Worker>(service, "standby") == null && Field<HashSet<Worker>>(service, "workers").Count == 0);
                }
                service.PowerChanged(PowerBroadcastStatus.ResumeAutomatic); Check(Field<Worker>(service, "standby") == null);
            }
            using (var service = new SignInService(root, 80)) {
                Invoke(service, "PrepareWorker"); var prepared = Field<Worker>(service, "standby"); Check(prepared != null);
                using (var process = Process.GetProcessById(prepared.ProcessId)) {
                    Check(process.WaitForExit(3000)); await Task.Delay(50);
                    Check(Field<Worker>(service, "standby") == null && Field<HashSet<Worker>>(service, "workers").Count == 0);
                }
            }
            using (var service = new SignInService(root, 60000)) {
                Invoke(service, "PrepareWorker"); var prepared = Field<Worker>(service, "standby"); await prepared.Ready;
                using (var process = Process.GetProcessById(prepared.ProcessId)) {
                    // Invalid profile is rejected before the verify command can
                    // request a camera, while exercising actual standby consumption.
                    var consumed = (Task)typeof(SignInService).GetMethod("WithWorker", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(service, new object[] {
                        new Account { Profile = "{}" }, "verify", new Func<Worker, Task>(async delegate(Worker worker) {
                            Check(worker == prepared && Convert.ToString((await worker.Next())["event"]) == "error");
                        }), Field<int>(service, "powerGeneration")
                    });
                    await consumed; Check(process.WaitForExit(3000));
                    var deadline = Stopwatch.StartNew();
                    while (Field<Worker>(service, "standby") == null && deadline.ElapsedMilliseconds < 3000) await Task.Delay(10);
                    var replacement = Field<Worker>(service, "standby");
                    Check(replacement != null && replacement != prepared && Field<HashSet<Worker>>(service, "workers").Count == 1);
                    await replacement.Ready;
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
                using (var service = new SignInService(failedRoot, 60000)) {
                    Invoke(service, "PrepareWorker"); var prepared = Field<Worker>(service, "standby"); Check(prepared != null);
                    try { await prepared.Ready; throw new Exception("Expected failed warmup."); } catch (IOException) { Check(true); }
                    var deadline = Stopwatch.StartNew();
                    while (Field<Worker>(service, "standby") != null && deadline.ElapsedMilliseconds < 2000) await Task.Delay(10);
                    Check(Field<Worker>(service, "standby") == null && Field<HashSet<Worker>>(service, "workers").Count == 0 && !prepared.IsAlive);
                }
            } finally { Directory.Delete(failedRoot, true); }
        }
    }
}
