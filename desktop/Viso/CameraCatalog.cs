using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

namespace Viso
{
    internal static class CameraCatalog
    {
        [ComImport, Guid("29840822-5B84-11D0-BD3B-00A0C911CE86"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface ICreateDevEnum { [PreserveSig] int CreateClassEnumerator([In] ref Guid category, out IEnumMoniker enumerator, int flags); }
        [ComImport, Guid("55272A00-42CB-11CE-8135-00AA004BB851"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IPropertyBag {
            [PreserveSig] int Read([MarshalAs(UnmanagedType.LPWStr)] string name, [In, Out, MarshalAs(UnmanagedType.Struct)] ref object value, IntPtr errorLog);
            [PreserveSig] int Write([MarshalAs(UnmanagedType.LPWStr)] string name, [In, MarshalAs(UnmanagedType.Struct)] ref object value);
        }
        public static List<string> List()
        {
            var names = new List<string>();
            object deviceEnum = null;
            IEnumMoniker enumerator = null;
            try
            {
                deviceEnum = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("62BE5D10-60EB-11D0-BD3B-00A0C911CE86")));
                Guid category = new Guid("860BB310-5D01-11D0-BD3B-00A0C911CE86");
                if (((ICreateDevEnum)deviceEnum).CreateClassEnumerator(ref category, out enumerator, 0) != 0) return names;
                var monikers = new IMoniker[1];
                while (enumerator.Next(1, monikers, IntPtr.Zero) == 0)
                {
                    object bag = null;
                    try
                    {
                        Guid bagId = typeof(IPropertyBag).GUID;
                        monikers[0].BindToStorage(null, null, ref bagId, out bag);
                        object name = null;
                        ((IPropertyBag)bag).Read("FriendlyName", ref name, IntPtr.Zero);
                        names.Add(Convert.ToString(name) ?? "Camera " + (names.Count + 1));
                    }
                    finally { if (bag != null) Marshal.ReleaseComObject(bag); Marshal.ReleaseComObject(monikers[0]); }
                }
            }
            catch { if (names.Count == 0) names.Add("Default camera"); }
            finally { if (enumerator != null) Marshal.ReleaseComObject(enumerator); if (deviceEnum != null) Marshal.ReleaseComObject(deviceEnum); }
            return names;
        }
    }
}
