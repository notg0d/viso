using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using System.Windows;
using System.Windows.Markup;

[assembly: AssemblyTitle("Viso")]
[assembly: AssemblyDescription("Native Windows face enrollment and recognition")]
[assembly: AssemblyVersion("0.7.0.0")]

namespace Viso
{
    internal static class Program
    {
        [STAThread]
        public static int Main(string[] args)
        {
            try
            {
                string root = AppDomain.CurrentDomain.BaseDirectory;
                while (!Directory.Exists(Path.Combine(root, "backend")))
                {
                    var parent = Directory.GetParent(root);
                    if (parent == null) throw new DirectoryNotFoundException("Keep Viso.exe in the Viso project folder.");
                    root = parent.FullName;
                }
                string instanceKey;
                using (var hash = SHA256.Create()) instanceKey = BitConverter.ToString(hash.ComputeHash(System.Text.Encoding.UTF8.GetBytes(root.ToLowerInvariant()))).Replace("-", "");
                bool first;
                using (var instance = new Mutex(true, "Local\\Viso-" + instanceKey + (args.Contains("--smoke-test") ? "-smoke" : ""), out first))
                {
                    if (!first) { MessageBox.Show("Viso is already open. Use the running window, or close it before switching storage modes.", "Viso", MessageBoxButton.OK, MessageBoxImage.Information); return 0; }
                    var app = new Application { ShutdownMode = ShutdownMode.OnMainWindowClose };
                    Window window;
                    using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("Viso.MainWindow.xaml"))
                        window = (Window)XamlReader.Load(stream);
                    var controller = new MainWindow(window, root, args.Contains("--ephemeral"), args.Contains("--smoke-test"));
                    app.Run(window);
                    GC.KeepAlive(controller);
                    instance.ReleaseMutex();
                    return controller.ExitCode;
                }
            }
            catch (Exception error)
            {
                if (args.Contains("--smoke-test")) File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "smoke-error.txt"), error.ToString());
                else MessageBox.Show(error.Message, "Viso", MessageBoxButton.OK, MessageBoxImage.Error);
                return 1;
            }
        }
    }
}
