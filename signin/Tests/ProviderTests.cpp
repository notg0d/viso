#define SECURITY_WIN32
#define _SEC_WINNT_AUTH_TYPES
#include "../Provider/Provider.cpp"
#include <ntsecapi.h>
#include <sspi.h>
#include <wincred.h>
#include <iostream>
#include <cassert>
#include <algorithm>

class User final : public ICredentialProviderUser
{
    ULONG refs = 1;
    bool local;
    std::wstring name, sid;
public:
    User(bool local, std::wstring name, std::wstring sid) : local(local), name(name), sid(sid) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** value) override { *value = nullptr; if (iid != IID_IUnknown && iid != IID_ICredentialProviderUser) return E_NOINTERFACE; *value = this; AddRef(); return S_OK; }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { auto count = --refs; if (!count) delete this; return count; }
    HRESULT STDMETHODCALLTYPE GetSid(PWSTR* value) override { return Copy(sid, value); }
    HRESULT STDMETHODCALLTYPE GetProviderID(GUID* value) override { *value = local ? Identity_LocalUserProvider : GUID{}; return S_OK; }
    HRESULT STDMETHODCALLTYPE GetStringValue(REFPROPERTYKEY key, PWSTR* value) override { if (key == PKEY_Identity_QualifiedUserName) return Copy(name, value); *value = nullptr; return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetValue(REFPROPERTYKEY, PROPVARIANT*) override { return E_NOTIMPL; }
};
class Users final : public ICredentialProviderUserArray
{
    ULONG refs = 1;
public:
    std::vector<User*> users;
    ~Users() { for (auto user : users) user->Release(); }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** value) override { *value = nullptr; if (iid != IID_IUnknown && iid != IID_ICredentialProviderUserArray) return E_NOINTERFACE; *value = this; AddRef(); return S_OK; }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { auto count = --refs; if (!count) delete this; return count; }
    HRESULT STDMETHODCALLTYPE SetProviderFilter(REFGUID) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE GetAccountOptions(CREDENTIAL_PROVIDER_ACCOUNT_OPTIONS* value) override { *value = CPAO_NONE; return S_OK; }
    HRESULT STDMETHODCALLTYPE GetCount(DWORD* value) override { *value = static_cast<DWORD>(users.size()); return S_OK; }
    HRESULT STDMETHODCALLTYPE GetAt(DWORD index, ICredentialProviderUser** user) override { if (index >= users.size()) return E_INVALIDARG; *user = users[index]; (*user)->AddRef(); return S_OK; }
};

static void Free(CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION& value)
{
    SecureZeroMemory(value.rgbSerialization, value.cbSerialization); CoTaskMemFree(value.rgbSerialization); value = {};
}
template<typename T> static T Function(HMODULE module, const char* name)
{
    FARPROC address = GetProcAddress(module, name); assert(address);
    T result; static_assert(sizeof(result) == sizeof(address)); memcpy(&result, &address, sizeof(result)); return result;
}
int wmain()
{
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    HMODULE sspi = LoadLibraryExW(L"sspicli.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32); assert(sspi);
    auto decrypt = Function<decltype(&SspiDecryptAuthIdentityEx)>(sspi, "SspiDecryptAuthIdentityEx");
    wchar_t machine[MAX_COMPUTERNAME_LENGTH + 1]; DWORD length = ARRAYSIZE(machine); assert(GetComputerNameW(machine, &length));
    const std::wstring localName = std::wstring(machine) + L"\\VisoTest";
    const std::wstring secret = L"Fake-only Unicode p\u00e4ss\u674e!";
    for (auto scenario : {CPUS_LOGON, CPUS_UNLOCK_WORKSTATION}) {
        CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION packed = {};
        assert(SUCCEEDED(PackCredential(true, localName, secret, scenario, &packed)));
        auto logon = reinterpret_cast<KERB_INTERACTIVE_UNLOCK_LOGON*>(packed.rgbSerialization);
        assert(logon->Logon.MessageType == (scenario == CPUS_LOGON ? KerbInteractiveLogon : KerbWorkstationUnlockLogon));
        auto read = [&](const UNICODE_STRING& field) { auto offset = reinterpret_cast<size_t>(field.Buffer); assert(offset + field.Length <= packed.cbSerialization); return std::wstring(reinterpret_cast<wchar_t*>(packed.rgbSerialization + offset), field.Length / 2); };
        assert(read(logon->Logon.UserName) == L"VisoTest"); assert(read(logon->Logon.LogonDomainName) == machine);
        auto protectedPassword = read(logon->Logon.Password); DWORD count = 1024; wchar_t clear[1024] = {};
        assert(CredUnprotectW(FALSE, protectedPassword.data(), static_cast<DWORD>(protectedPassword.size() + 1), clear, &count));
        assert(secret == clear); SecureZeroMemory(clear, sizeof(clear)); Erase(protectedPassword); Free(packed);
        assert(SUCCEEDED(PackCredential(false, L"MicrosoftAccount\\viso-test@example.com", secret, scenario, &packed)));
        // Online-identity credentials unpack as marshaled strings, rather than a
        // plaintext password. Verify the actual SSPI identity after decryption.
        PSEC_WINNT_AUTH_IDENTITY_OPAQUE identity = nullptr;
        assert(SspiUnmarshalAuthIdentity(packed.cbSerialization, reinterpret_cast<char*>(packed.rgbSerialization), &identity) == SEC_E_OK);
        assert(decrypt(SEC_WINNT_AUTH_IDENTITY_ENCRYPT_SAME_LOGON, identity) == SEC_E_OK);
        auto decoded = reinterpret_cast<SEC_WINNT_AUTH_IDENTITY_EX2*>(identity);
        assert(decoded->Version == SEC_WINNT_AUTH_IDENTITY_VERSION_2 && decoded->cbStructureLength <= 65536);
        auto bytes = reinterpret_cast<BYTE*>(identity);
        auto contains = [&](const std::wstring& text) { auto pattern = reinterpret_cast<const BYTE*>(text.data()); return std::search(bytes, bytes + decoded->cbStructureLength, pattern, pattern + text.size() * 2) != bytes + decoded->cbStructureLength; };
        assert(contains(secret)); assert(contains(L"viso-test@example.com"));
        SspiZeroAuthIdentity(identity); SspiFreeAuthIdentity(identity); Free(packed);
    }
    CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION invalid = {};
    assert(FAILED(PackCredential(false, L"AzureAD\\test@example.com", secret, CPUS_LOGON, &invalid)));
    assert(FAILED(PackCredential(true, localName, secret, CPUS_CREDUI, &invalid)));
    assert(FAILED(PackCredential(true, localName, L"", CPUS_LOGON, &invalid)));
    auto provider = new Provider();
    assert(provider->SetUsageScenario(CPUS_CREDUI, 0) == E_NOTIMPL);
    assert(SUCCEEDED(provider->SetUsageScenario(CPUS_LOGON, 0)));
    auto users = new Users();
    users->users.push_back(new User(true, localName, L"S-1-5-21-1-2-3-1001"));
    users->users.push_back(new User(false, L"MicrosoftAccount\\viso-test@example.com", L"S-1-5-21-1-2-3-1002"));
    users->users.push_back(new User(true, L"WORKDOMAIN\\Other", L"S-1-5-21-1-2-3-1003"));
    users->users.push_back(new User(false, L"AzureAD\\Other", L"S-1-5-21-1-2-3-1004"));
    assert(SUCCEEDED(provider->SetUserArray(users))); users->Release();
    DWORD count, defaultIndex; BOOL automatic;
    provider->GetCredentialCount(&count, &defaultIndex, &automatic);
    assert(count == 2 && defaultIndex == CREDENTIAL_PROVIDER_NO_DEFAULT && !automatic);
    for (DWORD i = 0; i < count; ++i) {
        ICredentialProviderCredential* credential = nullptr; assert(SUCCEEDED(provider->GetCredentialAt(i, &credential)));
        ICredentialProviderCredential2* v2 = nullptr; assert(SUCCEEDED(credential->QueryInterface(IID_PPV_ARGS(&v2))));
        PWSTR sid = nullptr; v2->GetUserSid(&sid); assert(std::wstring(sid) == (i ? L"S-1-5-21-1-2-3-1002" : L"S-1-5-21-1-2-3-1001")); CoTaskMemFree(sid); v2->Release();
        for (int attempt = 0; attempt < 2; ++attempt) {
            CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE response; PWSTR text = nullptr; CREDENTIAL_PROVIDER_STATUS_ICON icon;
            assert(SUCCEEDED(credential->GetSerialization(&response, &invalid, &text, &icon)));
            assert(response == CPGSR_NO_CREDENTIAL_NOT_FINISHED && invalid.rgbSerialization == nullptr);
            CoTaskMemFree(text);
        }
        credential->Release();
    }
    provider->Release(); assert(DllCanUnloadNow() == S_OK);
    wchar_t executable[32768]; assert(GetModuleFileNameW(nullptr, executable, ARRAYSIZE(executable)));
    std::wstring dll = executable; dll = dll.substr(0, dll.find_last_of(L'\\') + 1) + L"VisoCredentialProvider.dll";
    HMODULE module = LoadLibraryExW(dll.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32); assert(module);
    auto factoryEntry = Function<decltype(&DllGetClassObject)>(module, "DllGetClassObject");
    IClassFactory* factory = nullptr; assert(SUCCEEDED(factoryEntry(CLSID_Viso, IID_IClassFactory, reinterpret_cast<void**>(&factory))));
    ICredentialProvider* actual = nullptr; assert(SUCCEEDED(factory->CreateInstance(nullptr, IID_ICredentialProvider, reinterpret_cast<void**>(&actual))));
    assert(actual->SetUsageScenario(CPUS_CREDUI, 0) == E_NOTIMPL); actual->Release(); factory->Release();
    assert(Function<decltype(&DllCanUnloadNow)>(module, "DllCanUnloadNow")() == S_OK);
    FreeLibrary(module); FreeLibrary(sspi);
    CoUninitialize(); std::cout << "Provider checks passed: actual DLL activation, local/MSA logon+unlock packing, Unicode, account filtering, no default takeover, and no credentials before verification.\n";
}
