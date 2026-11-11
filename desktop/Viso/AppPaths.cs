using System;
using System.IO;

namespace Viso
{
    internal static class AppPaths
    {
        public static string DataDirectory(string root)
        {
            string installed = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Viso");
            // The protected all-users installation is read-only to ordinary users.
            // Portable/source copies deliberately retain their existing .viso folder.
            if (Path.GetFullPath(root).TrimEnd('\\').Equals(installed, StringComparison.OrdinalIgnoreCase))
                return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Viso");
            return Path.Combine(root, ".viso");
        }
    }
}
