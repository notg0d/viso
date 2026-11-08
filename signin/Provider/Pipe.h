#pragma once
#include "Auth.h"
#include <vector>
#include <stdexcept>
#include <functional>

class Pipe final
{
    HANDLE handle = INVALID_HANDLE_VALUE;
    IQueryContinueWithStatus* query;
    std::function<bool()> active;
    ULONGLONG started = GetTickCount64();
    void Check()
    {
        if (GetTickCount64() - started > 60000 || !active() || (query && query->QueryContinue() != S_OK)) throw std::runtime_error("canceled");
    }
    void Transfer(void* data, DWORD size, bool write)
    {
        DWORD offset = 0;
        while (offset < size) {
            Check();
            OVERLAPPED operation = {}; operation.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
            if (!operation.hEvent) throw std::runtime_error("event");
            DWORD count = 0;
            BOOL ok = write ? WriteFile(handle, static_cast<BYTE*>(data) + offset, size - offset, &count, &operation)
                : ReadFile(handle, static_cast<BYTE*>(data) + offset, size - offset, &count, &operation);
            try {
                if (!ok && GetLastError() != ERROR_IO_PENDING) throw std::runtime_error("pipe");
                if (!ok) {
                    while (WaitForSingleObject(operation.hEvent, 100) == WAIT_TIMEOUT) Check();
                    if (!GetOverlappedResult(handle, &operation, &count, FALSE)) throw std::runtime_error("pipe");
                }
                if (!count) throw std::runtime_error("closed");
            } catch (...) {
                CancelIoEx(handle, &operation); GetOverlappedResult(handle, &operation, &count, TRUE); CloseHandle(operation.hEvent); throw;
            }
            CloseHandle(operation.hEvent); offset += count;
        }
    }
public:
    struct Message : std::vector<std::wstring> { ~Message() { for (auto& value : *this) Erase(value); } };
    Pipe(IQueryContinueWithStatus* status, std::function<bool()> active) : query(status), active(std::move(active))
    {
        Check();
        const auto path = L"\\\\.\\pipe\\Viso.SignIn.v1";
        if (!WaitNamedPipeW(path, 2000) && GetLastError() != ERROR_SEM_TIMEOUT) throw std::runtime_error("unavailable");
        Check();
        handle = CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_IMPERSONATION, nullptr);
        if (handle == INVALID_HANDLE_VALUE) throw std::runtime_error("unavailable");
        ULONG pid = 0; SERVICE_STATUS_PROCESS serviceStatus = {}; DWORD needed = 0;
        SC_HANDLE manager = OpenSCManagerW(nullptr, nullptr, SC_MANAGER_CONNECT);
        SC_HANDLE service = manager ? OpenServiceW(manager, L"VisoSignIn", SERVICE_QUERY_STATUS) : nullptr;
        bool trusted = GetNamedPipeServerProcessId(handle, &pid) && service && QueryServiceStatusEx(service, SC_STATUS_PROCESS_INFO, reinterpret_cast<BYTE*>(&serviceStatus), sizeof(serviceStatus), &needed)
            && serviceStatus.dwCurrentState == SERVICE_RUNNING && serviceStatus.dwProcessId == pid;
        if (service) CloseServiceHandle(service); if (manager) CloseServiceHandle(manager);
        if (!trusted) { CloseHandle(handle); handle = INVALID_HANDLE_VALUE; throw std::runtime_error("untrusted service"); }
    }
    ~Pipe() { if (handle != INVALID_HANDLE_VALUE) CloseHandle(handle); }
    void Send(std::initializer_list<std::wstring> fields)
    {
        std::vector<BYTE> body;
        auto number = [&](DWORD value) { for (int i = 0; i < 4; ++i) body.push_back(static_cast<BYTE>(value >> (i * 8))); };
        number(1); number(static_cast<DWORD>(fields.size()));
        for (auto& field : fields) {
            int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, field.data(), static_cast<int>(field.size()), nullptr, 0, nullptr, nullptr);
            if (length < 0 || (!field.empty() && !length)) throw std::runtime_error("encoding");
            number(length); size_t offset = body.size(); body.resize(offset + length);
            if (length) WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, field.data(), static_cast<int>(field.size()), reinterpret_cast<char*>(body.data() + offset), length, nullptr, nullptr);
        }
        DWORD size = static_cast<DWORD>(body.size());
        Transfer(&size, 4, true); Transfer(body.data(), size, true);
    }
    Message Receive()
    {
        DWORD size = 0; Transfer(&size, 4, false);
        if (size < 8 || size > 262144) throw std::runtime_error("frame");
        std::vector<BYTE> body(size);
        struct Wipe { std::vector<BYTE>& value; ~Wipe() { SecureZeroMemory(value.data(), value.size()); } } wipe{body};
        Transfer(body.data(), size, false);
        size_t offset = 0;
        auto number = [&]() -> DWORD { if (offset + 4 > size) throw std::runtime_error("frame"); DWORD value; memcpy(&value, body.data() + offset, 4); offset += 4; return value; };
        if (number() != 1) throw std::runtime_error("version");
        DWORD count = number(); if (count < 1 || count > 16) throw std::runtime_error("fields");
        Message result;
        for (DWORD i = 0; i < count; ++i) {
            DWORD length = number(); if (length > size - offset) throw std::runtime_error("length");
            int chars = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, reinterpret_cast<char*>(body.data() + offset), length, nullptr, 0);
            if (length && chars <= 0) throw std::runtime_error("encoding");
            result.emplace_back(chars, L'\0');
            auto& field = result.back();
            if (chars) MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, reinterpret_cast<char*>(body.data() + offset), length, field.data(), chars);
            if (field.find(L'\0') != std::wstring::npos) { Erase(field); throw std::runtime_error("null"); }
            offset += length;
        }
        if (offset != size) throw std::runtime_error("trailing");
        return result;
    }
};
