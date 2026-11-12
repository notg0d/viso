using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using Viso.SignIn;

namespace Viso
{
    internal static class SignInSettings
    {
        public static bool IsInstalled { get { using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SYSTEM\CurrentControlSet\Services\VisoSignIn")) return key != null; } }
        public static async Task<string> Status()
        {
            try { return (await Wire.Request("status"))[1]; }
            catch (TimeoutException) { return "Sign-in components are not installed or the service is stopped. Run scripts\\install-signin.ps1 from an administrator PowerShell."; }
            catch (IOException) { return "Sign-in service unavailable. Check the VisoSignIn Windows service."; }
        }
        public static Task<string[]> CameraStatus() { return Wire.Request("status"); }
        public static async Task<string> SaveCamera(int camera, bool exposureAssist)
        {
            return (await Wire.Request("camera.settings", camera.ToString(System.Globalization.CultureInfo.InvariantCulture), exposureAssist ? "true" : "false"))[1];
        }
        public static async Task<string> Link(string dataDirectory, string kind, string user, string password, int camera, bool exposureAssist)
        {
            string path = Path.Combine(dataDirectory, "profile.dpapi");
            if (!File.Exists(path) || new FileInfo(path).Length > 131072) throw new InvalidOperationException("Complete and save a camera enrollment first.");
            byte[] clear = ProtectedData.Unprotect(File.ReadAllBytes(path), null, DataProtectionScope.CurrentUser);
            try { return (await Wire.Request("link", kind, user, password, Encoding.UTF8.GetString(clear), camera.ToString(System.Globalization.CultureInfo.InvariantCulture), exposureAssist ? "true" : "false"))[1]; }
            finally { Array.Clear(clear, 0, clear.Length); }
        }
        public static async Task<string> Unlink() { return (await Wire.Request("unlink"))[1]; }
    }
}
