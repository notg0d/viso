using System;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading.Tasks;

namespace Viso.SignIn
{
    // One bounded, length-prefixed UTF-8 string-array per message, protocol version 1.
    // No delimiter escaping, arbitrary object deserialization, or password logging.
    internal static class Wire
    {
        public const string PipeName = "Viso.SignIn.v1";
        public const int Limit = 262144;
        private static readonly Encoding Utf8 = new UTF8Encoding(false, true);

        public static byte[] Encode(params string[] values)
        {
            if (values == null || values.Length < 1 || values.Length > 16) throw new InvalidDataException("Invalid field count.");
            int size = 8;
            var lengths = new int[values.Length];
            for (int i = 0; i < values.Length; i++) {
                lengths[i] = Utf8.GetByteCount(values[i] ?? "");
                if (lengths[i] > Limit - size - 4) throw new InvalidDataException("Sign-in message is too large.");
                size += 4 + lengths[i];
            }
            var body = new byte[size];
            try {
                // One buffer, with no leftover MemoryStream copy of the password.
                Buffer.BlockCopy(BitConverter.GetBytes(1), 0, body, 0, 4);
                Buffer.BlockCopy(BitConverter.GetBytes(values.Length), 0, body, 4, 4);
                int offset = 8;
                for (int i = 0; i < values.Length; i++) {
                    Buffer.BlockCopy(BitConverter.GetBytes(lengths[i]), 0, body, offset, 4); offset += 4;
                    string value = values[i] ?? "";
                    Utf8.GetBytes(value, 0, value.Length, body, offset); offset += lengths[i];
                }
                return body;
            } catch { Array.Clear(body, 0, body.Length); throw; }
        }

        public static string[] Decode(byte[] bytes)
        {
            if (bytes.Length > Limit) throw new InvalidDataException("Sign-in message is too large.");
            using (var reader = new BinaryReader(new MemoryStream(bytes), Utf8)) {
                if (reader.ReadInt32() != 1) throw new InvalidDataException("Incompatible sign-in protocol.");
                int count = reader.ReadInt32();
                if (count < 1 || count > 16) throw new InvalidDataException("Invalid field count.");
                var values = new string[count];
                for (int i = 0; i < count; i++) {
                    int length = reader.ReadInt32();
                    if (length < 0 || length > reader.BaseStream.Length - reader.BaseStream.Position) throw new InvalidDataException("Invalid field length.");
                    byte[] field = reader.ReadBytes(length);
                    try { values[i] = Utf8.GetString(field); }
                    finally { Array.Clear(field, 0, field.Length); }
                    if (values[i].IndexOf('\0') >= 0) throw new InvalidDataException("Embedded null characters are not supported.");
                }
                if (reader.BaseStream.Position != bytes.Length) throw new InvalidDataException("Trailing sign-in data.");
                return values;
            }
        }

        public static async Task Send(Stream stream, params string[] values)
        {
            byte[] body = Encode(values);
            try {
                byte[] size = BitConverter.GetBytes(body.Length);
                await stream.WriteAsync(size, 0, size.Length).ConfigureAwait(false);
                await stream.WriteAsync(body, 0, body.Length).ConfigureAwait(false);
                await stream.FlushAsync().ConfigureAwait(false);
            } finally { Array.Clear(body, 0, body.Length); }
        }

        private static async Task ReadExact(Stream stream, byte[] bytes)
        {
            int offset = 0;
            while (offset < bytes.Length) {
                int count = await stream.ReadAsync(bytes, offset, bytes.Length - offset).ConfigureAwait(false);
                if (count == 0) throw new EndOfStreamException();
                offset += count;
            }
        }

        public static async Task<string[]> Receive(Stream stream)
        {
            var header = new byte[4]; await ReadExact(stream, header).ConfigureAwait(false);
            int length = BitConverter.ToInt32(header, 0);
            if (length < 8 || length > Limit) throw new InvalidDataException("Invalid sign-in frame size.");
            var body = new byte[length];
            try { await ReadExact(stream, body).ConfigureAwait(false); return Decode(body); }
            finally { Array.Clear(body, 0, body.Length); }
        }

        public static async Task<string[]> Request(params string[] fields)
        {
            // GENERIC_WRITE also asks for CreateNewInstance on named pipes. Request
            // explicit data rights to match the service's non-server client ACL.
            using (var pipe = new NamedPipeClientStream(".", PipeName, PipeAccessRights.ReadWrite, PipeOptions.Asynchronous, System.Security.Principal.TokenImpersonationLevel.Impersonation, HandleInheritability.None)) {
                await pipe.ConnectAsync(2500).ConfigureAwait(false);
                Native.TrustServer(pipe);
                var task = Exchange(pipe, fields);
                if (await Task.WhenAny(task, Task.Delay(30000)).ConfigureAwait(false) != task) {
                    ObserveFailure(task);
                    throw new TimeoutException("Windows sign-in service timed out.");
                }
                return await task.ConfigureAwait(false);
            }
        }
        private static void ObserveFailure(Task task)
        {
            task.ContinueWith(delegate(Task failed) { var ignored = failed.Exception; }, TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously);
        }
        private static async Task<string[]> Exchange(Stream pipe, string[] fields)
        {
            await Send(pipe, fields).ConfigureAwait(false);
            var response = await Receive(pipe).ConfigureAwait(false);
            if (response[0] != "ok") throw new InvalidOperationException(response.Length > 1 ? response[1] : "Windows sign-in request failed.");
            return response;
        }
    }
}
