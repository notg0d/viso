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
class ScanEvents final : public ICredentialProviderEvents, public ICredentialProviderCredentialEvents
{
    std::atomic<ULONG> refs{1};
    DWORD uiThread = GetCurrentThreadId();
public:
    HANDLE completed = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    std::atomic<int> starts{0}, submissions{0};
    ~ScanEvents() { CloseHandle(completed); }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** value) override {
        *value = nullptr;
        if (iid == IID_IUnknown || iid == IID_ICredentialProviderEvents) *value = static_cast<ICredentialProviderEvents*>(this);
        else if (iid == IID_ICredentialProviderCredentialEvents) *value = static_cast<ICredentialProviderCredentialEvents*>(this);
        else return E_NOINTERFACE;
        AddRef(); return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { auto count = --refs; if (!count) delete this; return count; }
    HRESULT STDMETHODCALLTYPE CredentialsChanged(UINT_PTR) override { assert(GetCurrentThreadId() == uiThread); ++submissions; return S_OK; }
    HRESULT STDMETHODCALLTYPE SetFieldString(ICredentialProviderCredential* tile, DWORD field, PCWSTR text) override {
        assert(tile && field == 2 && GetCurrentThreadId() == uiThread);
        if (std::wstring(text).find(L"Starting Viso") == 0) {
            ++starts;
            // Cancel before any connection to the real sign-in service.
            return E_ABORT;
        }
        SetEvent(completed); return S_OK;
    }
    HRESULT STDMETHODCALLTYPE SetFieldState(ICredentialProviderCredential*, DWORD, CREDENTIAL_PROVIDER_FIELD_STATE) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetFieldInteractiveState(ICredentialProviderCredential*, DWORD, CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetFieldCheckbox(ICredentialProviderCredential*, DWORD, BOOL, PCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetFieldBitmap(ICredentialProviderCredential*, DWORD, HBITMAP) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetFieldComboBoxSelectedItem(ICredentialProviderCredential*, DWORD, DWORD) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE DeleteFieldComboBoxItem(ICredentialProviderCredential*, DWORD, DWORD) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE AppendFieldComboBoxItem(ICredentialProviderCredential*, DWORD, PCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE SetFieldSubmitButton(ICredentialProviderCredential*, DWORD, DWORD) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE OnCreatingWindow(HWND* value) override { *value = nullptr; return S_OK; }
};
static void WaitForScan(HANDLE handle)
{
    auto deadline = GetTickCount64() + 5000;
    while (WaitForSingleObject(handle, 0) != WAIT_OBJECT_0 && GetTickCount64() < deadline) {
        MsgWaitForMultipleObjects(1, &handle, FALSE, 100, QS_ALLINPUT);
        MSG message;
        while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) { TranslateMessage(&message); DispatchMessageW(&message); }
    }
    assert(WaitForSingleObject(handle, 0) == WAIT_OBJECT_0);
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
    auto events = new ScanEvents();
    auto automaticTile = new Credential(L"S-1-5-21-1-2-3-1001", localName, true, CPUS_LOGON);
    automaticTile->SetProviderEvents(events, 42);
    automaticTile->Advise(events);
    automatic = TRUE;
    assert(SUCCEEDED(automaticTile->SetSelected(&automatic)) && !automatic);
    WaitForScan(events->completed);
    assert(events->starts == 1 && events->submissions == 0 && !automaticTile->HasCredential());
    // Repeated selection after failure cannot create an automatic retry loop.
    automaticTile->SetSelected(&automatic);
    assert(!automatic && events->starts == 1);
    automaticTile->SetDeselected(); ResetEvent(events->completed);
    automaticTile->SetSelected(&automatic); WaitForScan(events->completed);
    assert(events->starts == 2 && events->submissions == 0);
    // Deselect before dispatching the posted start: stale UI callbacks disappear.
    automaticTile->SetDeselected(); automaticTile->SetSelected(&automatic); automaticTile->SetDeselected();
    MSG canceledMessage;
    while (PeekMessageW(&canceledMessage, nullptr, 0, 0, PM_REMOVE)) DispatchMessageW(&canceledMessage);
    assert(events->starts == 2 && events->submissions == 0 && !automaticTile->HasCredential());
    automaticTile->Detach(); automaticTile->Release();
    // Drain pending callbacks while the canceled worker releases its reference.
    auto deadline = GetTickCount64() + 5000;
    HANDLE pause = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    while (DllCanUnloadNow() != S_OK && GetTickCount64() < deadline) {
        DWORD index; CoWaitForMultipleHandles(COWAIT_DISPATCH_CALLS | COWAIT_DISPATCH_WINDOW_MESSAGES, 10, 1, &pause, &index);
    }
    CloseHandle(pause); assert(DllCanUnloadNow() == S_OK); events->Release();
    wchar_t executable[32768]; assert(GetModuleFileNameW(nullptr, executable, ARRAYSIZE(executable)));
    std::wstring dll = executable; dll = dll.substr(0, dll.find_last_of(L'\\') + 1) + L"VisoCredentialProvider.dll";
    HMODULE module = LoadLibraryExW(dll.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32); assert(module);
    auto factoryEntry = Function<decltype(&DllGetClassObject)>(module, "DllGetClassObject");
    IClassFactory* factory = nullptr; assert(SUCCEEDED(factoryEntry(CLSID_Viso, IID_IClassFactory, reinterpret_cast<void**>(&factory))));
    ICredentialProvider* actual = nullptr; assert(SUCCEEDED(factory->CreateInstance(nullptr, IID_ICredentialProvider, reinterpret_cast<void**>(&actual))));
    assert(actual->SetUsageScenario(CPUS_CREDUI, 0) == E_NOTIMPL);
    assert(SUCCEEDED(actual->SetUsageScenario(CPUS_LOGON, 0)));
    auto actualEvents = new ScanEvents(); actual->Advise(actualEvents, 42);
    ICredentialProviderSetUserArray* actualUsers = nullptr; assert(SUCCEEDED(actual->QueryInterface(IID_PPV_ARGS(&actualUsers))));
    auto oneUser = new Users(); oneUser->users.push_back(new User(true, localName, L"S-1-5-21-1-2-3-1001"));
    actualUsers->SetUserArray(oneUser); oneUser->Release(); actualUsers->Release();
    ICredentialProviderCredential* actualTile = nullptr; assert(SUCCEEDED(actual->GetCredentialAt(0, &actualTile)));
    actualTile->Advise(actualEvents); actualTile->SetSelected(&automatic); WaitForScan(actualEvents->completed);
    assert(actualEvents->starts == 1 && actualEvents->submissions == 0);
    actualTile->SetDeselected(); actualTile->UnAdvise(); actualTile->Release();
    actual->UnAdvise(); actual->Release(); factory->Release();
    auto canUnload = Function<decltype(&DllCanUnloadNow)>(module, "DllCanUnloadNow");
    deadline = GetTickCount64() + 5000;
    while (canUnload() != S_OK && GetTickCount64() < deadline) {
        MSG message;
        while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) DispatchMessageW(&message);
        SwitchToThread();
    }
    assert(canUnload() == S_OK); actualEvents->Release();
    FreeLibrary(module); FreeLibrary(sspi);
    CoUninitialize(); std::cout << "Provider checks passed: DLL activation, protected local/MSA packing, account filtering, automatic scanning with UI-thread callbacks, bounded retry, cancellation, unload, and no credentials before verification.\n";
}
