using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;

namespace Viso.SignIn
{
    internal static class Native
    {
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint pid);
        [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetNamedPipeClientProcessId(SafePipeHandle pipe, out uint pid);
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr OpenSCManager(string machine, string database, uint access);
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr OpenService(IntPtr manager, string name, uint access);
        [DllImport("advapi32.dll", SetLastError = true)] private static extern bool QueryServiceStatusEx(IntPtr service, int level, out ServiceStatus status, int size, out int needed);
        [DllImport("advapi32.dll")] private static extern bool CloseServiceHandle(IntPtr handle);
        [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
        [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool LogonUser(string user, string domain, string password, int type, int provider, out IntPtr token);
        [StructLayout(LayoutKind.Sequential)] private struct ServiceStatus { public uint Type, State, Accepted, Win32Exit, ServiceExit, Checkpoint, WaitHint, Pid, Flags; }

        public static void TrustServer(NamedPipeClientStream pipe)
        {
            uint pid;
            if (!GetNamedPipeServerProcessId(pipe.SafePipeHandle, out pid)) throw new Win32Exception();
            IntPtr manager = OpenSCManager(null, null, 1), service = IntPtr.Zero;
            try {
                if (manager == IntPtr.Zero) throw new Win32Exception();
                service = OpenService(manager, "VisoSignIn", 4);
                ServiceStatus status; int needed;
                if (service == IntPtr.Zero || !QueryServiceStatusEx(service, 0, out status, Marshal.SizeOf(typeof(ServiceStatus)), out needed) || status.State != 4 || status.Pid != pid)
                    throw new UnauthorizedAccessException("The pipe does not belong to the installed Viso sign-in service.");
            } finally { if (service != IntPtr.Zero) CloseServiceHandle(service); if (manager != IntPtr.Zero) CloseServiceHandle(manager); }
        }

        public sealed class Caller
        {
            public string Sid;
            public bool System;
            public int Session;
            public string Image;
            public void RequireLogonUI()
            {
                string expected = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "LogonUI.exe");
                if (!System || Session <= 0 || !string.Equals(Image, expected, StringComparison.OrdinalIgnoreCase))
                    throw new UnauthorizedAccessException("Only Windows LogonUI may request a face sign-in.");
            }
        }

        public static Caller Identify(NamedPipeServerStream pipe)
        {
            var caller = new Caller();
            pipe.RunAsClient(delegate {
                using (var identity = WindowsIdentity.GetCurrent(true)) {
                    if (identity == null || identity.User == null || !identity.IsAuthenticated) throw new UnauthorizedAccessException();
                    caller.Sid = identity.User.Value; caller.System = identity.IsSystem;
                }
            });
            uint pid;
            if (!GetNamedPipeClientProcessId(pipe.SafePipeHandle, out pid)) throw new UnauthorizedAccessException();
            using (var process = Process.GetProcessById((int)pid)) {
                caller.Session = process.SessionId;
                if (caller.System) caller.Image = process.MainModule.FileName;
            }
            if (caller.Session <= 0) throw new UnauthorizedAccessException("Interactive Windows session required.");
            return caller;
        }

        public static string AccountName(string kind, string input)
        {
            input = (input ?? "").Trim();
            if (input.Length == 0 || input.Length > 256 || input.IndexOf('\0') >= 0) throw new ArgumentException("Enter your Windows account name.");
            if (kind == "microsoft") {
                const string prefix = "MicrosoftAccount\\";
                if (input.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) input = input.Substring(prefix.Length);
                if (!input.Contains("@") || input.Contains("\\") || input.Contains(" ")) throw new ArgumentException("Enter your Microsoft account email address.");
                return prefix + input;
            }
            if (kind != "local") throw new ArgumentException("Choose a local or Microsoft account.");
            int slash = input.IndexOf('\\');
            if (slash >= 0) {
                string domain = input.Substring(0, slash);
                if (domain != "." && !domain.Equals(Environment.MachineName, StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("Work/domain accounts are not supported.");
                input = input.Substring(slash + 1);
            }
            if (input.Length == 0 || input.Contains("\\") || input.Contains("@")) throw new ArgumentException("Enter the local Windows username.");
            return Environment.MachineName + "\\" + input;
        }

        public static void ValidatePassword(string qualified, string password, string expectedSid)
        {
            if (string.IsNullOrEmpty(password) || password.Length > 256) throw new ArgumentException("Enter the account password, rather than a Windows Hello PIN. Passwordless accounts need an account password for Viso sign-in.");
            int slash = qualified.IndexOf('\\'); IntPtr token;
            if (slash < 1 || !LogonUser(qualified.Substring(slash + 1), qualified.Substring(0, slash), password, 2, 0, out token))
                throw new InvalidOperationException("Windows could not verify that account password. For a Microsoft account, first sign into Windows once using its current password, then try linking again.");
            try {
                using (var identity = new WindowsIdentity(token)) {
                    if (identity.User.Value != expectedSid) throw new UnauthorizedAccessException("Link only the Windows account you are currently signed into.");
                }
            } finally { CloseHandle(token); }
        }
    }
}
