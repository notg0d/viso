using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace Viso.SignIn
{
    // Windows state controls only model residency, never authentication evidence.
    internal static class SessionState
    {
        [StructLayout(LayoutKind.Sequential)]
        internal struct Session { public int Id; public IntPtr Name; public int State; }
        [StructLayout(LayoutKind.Explicit, Size = 24)]
        private struct InfoPrefix
        {
            // WTSINFOEXW contains an eight-byte-aligned LEVEL1 union on x64.
            [FieldOffset(0)] public uint Level;
            [FieldOffset(8)] public uint SessionId;
            [FieldOffset(12)] public int State;
            [FieldOffset(16)] public int Flags;
        }
        [DllImport("kernel32.dll")] private static extern uint WTSGetActiveConsoleSessionId();
        [DllImport("wtsapi32.dll", CharSet = CharSet.Unicode)] private static extern bool WTSEnumerateSessionsW(IntPtr server, int reserved, int version, out IntPtr sessions, out int count);
        [DllImport("wtsapi32.dll", CharSet = CharSet.Unicode)] private static extern bool WTSQuerySessionInformationW(IntPtr server, int session, int infoClass, out IntPtr buffer, out int bytes);
        [DllImport("wtsapi32.dll")] private static extern void WTSFreeMemory(IntPtr memory);

        internal static bool NeedsModels(int changedSession, bool? awaitingSignIn)
        {
            uint console = WTSGetActiveConsoleSessionId();
            IntPtr sessions = IntPtr.Zero; int count;
            try {
                if (!WTSEnumerateSessionsW(IntPtr.Zero, 0, 1, out sessions, out count)) return true;
                var observed = new List<Session>();
                for (int index = 0; index < count; index++) {
                    observed.Add((Session)Marshal.PtrToStructure(IntPtr.Add(sessions, index * Marshal.SizeOf(typeof(Session))), typeof(Session)));
                }
                return NeedsModels(console, observed, changedSession, awaitingSignIn, AwaitingSignIn);
            } catch { return true; }
            finally { if (sessions != IntPtr.Zero) WTSFreeMemory(sessions); }
        }

        internal static bool NeedsModels(uint console, IEnumerable<Session> sessions, int changedSession, bool? awaitingSignIn, Func<int, bool> awaiting)
        {
            bool sawConsole = false;
            foreach (var session in sessions) {
                if (session.Id <= 0) continue;
                bool isConsole = (uint)session.Id == console;
                sawConsole |= isConsole;
                // Disconnected switched-out users do not keep models resident
                // while the console is unlocked. Connected locked users do.
                if (!isConsole && session.State != 0 && session.State != 1) continue;
                if (session.Id == changedSession && awaitingSignIn.HasValue) {
                    if (awaitingSignIn.Value) return true;
                    continue;
                }
                if (awaiting(session.Id)) return true;
            }
            // Before first logon, or during a console transition, keep one
            // model-only cache. Unknown state cannot authorize a scan.
            return !sawConsole;
        }

        private static bool AwaitingSignIn(int session)
        {
            IntPtr buffer = IntPtr.Zero; int bytes;
            try {
                // WTSUserName: inspect presence only; never return or log a name.
                if (!WTSQuerySessionInformationW(IntPtr.Zero, session, 5, out buffer, out bytes)) return true;
                if (bytes < 2 || buffer == IntPtr.Zero || Marshal.ReadInt16(buffer) == 0) return true;
            } finally { if (buffer != IntPtr.Zero) WTSFreeMemory(buffer); }
            buffer = IntPtr.Zero;
            try {
                // WTSSessionInfoEx; LOCK=0, UNLOCK=1 on supported Windows 10/11.
                if (!WTSQuerySessionInformationW(IntPtr.Zero, session, 25, out buffer, out bytes) || bytes < Marshal.SizeOf(typeof(InfoPrefix))) return true;
                var info = (InfoPrefix)Marshal.PtrToStructure(buffer, typeof(InfoPrefix));
                return info.Level != 1 || info.SessionId != (uint)session || info.Flags != 1;
            } finally { if (buffer != IntPtr.Zero) WTSFreeMemory(buffer); }
        }
    }
}
