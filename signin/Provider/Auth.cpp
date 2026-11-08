#define SECURITY_WIN32
#include "Auth.h"
#include <ntsecapi.h>
#include <wincred.h>
#include <vector>

static HRESULT Negotiate(ULONG* id)
{
    HANDLE lsa = nullptr;
    NTSTATUS status = LsaConnectUntrusted(&lsa);
    if (status != 0) return HRESULT_FROM_WIN32(LsaNtStatusToWinError(status));
    char name[] = "Negotiate";
    LSA_STRING package = {9, 10, name};
    status = LsaLookupAuthenticationPackage(lsa, &package, id);
    LsaDeregisterLogonProcess(lsa);
    return status == 0 ? S_OK : HRESULT_FROM_WIN32(LsaNtStatusToWinError(status));
}

HRESULT PackCredential(bool local, const std::wstring& qualified, const std::wstring& password,
    CREDENTIAL_PROVIDER_USAGE_SCENARIO scenario, CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* result)
{
    if (!result) return E_POINTER;
    *result = {};
    if ((scenario != CPUS_LOGON && scenario != CPUS_UNLOCK_WORKSTATION) || password.empty() || password.size() > 256 || qualified.size() > 256) return E_INVALIDARG;
    HRESULT hr = Negotiate(&result->ulAuthenticationPackage);
    if (FAILED(hr)) return hr;
    if (!local) {
        if (_wcsnicmp(qualified.c_str(), L"MicrosoftAccount\\", 17) != 0) return E_INVALIDARG;
        DWORD flags = CRED_PACK_PROTECTED_CREDENTIALS | CRED_PACK_ID_PROVIDER_CREDENTIALS;
        DWORD size = 0;
        CredPackAuthenticationBufferW(flags, const_cast<PWSTR>(qualified.c_str()), const_cast<PWSTR>(password.c_str()), nullptr, &size);
        if (GetLastError() != ERROR_INSUFFICIENT_BUFFER || size > 65536) return E_FAIL;
        result->rgbSerialization = static_cast<BYTE*>(CoTaskMemAlloc(size));
        if (!result->rgbSerialization) return E_OUTOFMEMORY;
        DWORD allocated = size;
        if (!CredPackAuthenticationBufferW(flags, const_cast<PWSTR>(qualified.c_str()), const_cast<PWSTR>(password.c_str()), result->rgbSerialization, &size)) {
            hr = HRESULT_FROM_WIN32(GetLastError()); SecureZeroMemory(result->rgbSerialization, allocated); CoTaskMemFree(result->rgbSerialization); *result = {}; return hr;
        }
        result->cbSerialization = size;
    } else {
        size_t slash = qualified.find(L'\\');
        if (slash == std::wstring::npos || slash == 0 || slash + 1 == qualified.size()) return E_INVALIDARG;
        std::wstring domain = qualified.substr(0, slash), user = qualified.substr(slash + 1);
        DWORD characters = 0; CRED_PROTECTION_TYPE type;
        CredProtectW(FALSE, const_cast<PWSTR>(password.c_str()), static_cast<DWORD>(password.size() + 1), nullptr, &characters, &type);
        if (GetLastError() != ERROR_INSUFFICIENT_BUFFER || characters > 8192) return E_FAIL;
        std::wstring protectedPassword(characters, L'\0');
        if (!CredProtectW(FALSE, const_cast<PWSTR>(password.c_str()), static_cast<DWORD>(password.size() + 1), protectedPassword.data(), &characters, &type)) {
            hr = HRESULT_FROM_WIN32(GetLastError()); Erase(protectedPassword); return hr;
        }
        protectedPassword.resize(wcslen(protectedPassword.c_str()));
        DWORD size = static_cast<DWORD>(sizeof(KERB_INTERACTIVE_UNLOCK_LOGON) + (domain.size() + user.size() + protectedPassword.size()) * sizeof(wchar_t));
        auto buffer = static_cast<BYTE*>(CoTaskMemAlloc(size));
        if (!buffer) { Erase(protectedPassword); return E_OUTOFMEMORY; }
        ZeroMemory(buffer, size);
        auto logon = reinterpret_cast<KERB_INTERACTIVE_UNLOCK_LOGON*>(buffer);
        logon->Logon.MessageType = scenario == CPUS_UNLOCK_WORKSTATION ? KerbWorkstationUnlockLogon : KerbInteractiveLogon;
        size_t offset = sizeof(*logon);
        auto append = [&](UNICODE_STRING& target, const std::wstring& value) {
            target.Length = target.MaximumLength = static_cast<USHORT>(value.size() * sizeof(wchar_t));
            memcpy(buffer + offset, value.data(), target.Length);
            target.Buffer = reinterpret_cast<PWSTR>(offset); offset += target.Length;
        };
        append(logon->Logon.LogonDomainName, domain); append(logon->Logon.UserName, user); append(logon->Logon.Password, protectedPassword);
        Erase(protectedPassword);
        result->rgbSerialization = buffer; result->cbSerialization = size;
    }
    result->clsidCredentialProvider = CLSID_Viso;
    return S_OK;
}
