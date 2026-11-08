#include <initguid.h>
#include "Auth.h"
#include "Pipe.h"
#include <shlwapi.h>
#include <shlguid.h>
#include <propkey.h>
#include <new>
#include <atomic>
#include <vector>
#include <mutex>
#include <thread>
#include <shlobj.h>
#include <commctrl.h>
#include <deque>
#include <memory>

static std::atomic<long> objects{0};
static HRESULT Copy(const std::wstring& value, PWSTR* result) { return SHStrDupW(value.c_str(), result); }

class Credential final : public ICredentialProviderCredential2, public IConnectableCredentialProviderCredential
{
    std::atomic<ULONG> refs{1};
    std::atomic<ULONGLONG> generation{0};
    std::mutex gate;
    std::wstring sid, qualified, kind, password;
    std::wstring detail = L"Look at the camera. Viso starts scanning when selected.";
    CREDENTIAL_PROVIDER_USAGE_SCENARIO scenario;
    ICredentialProviderCredentialEvents* events = nullptr;
    ICredentialProviderEvents* providerEvents = nullptr;
    UINT_PTR context = 0;
    bool selected = false, attempted = false, scanning = false;
    HWND scanWindow = nullptr;
    struct Update {
        ULONGLONG ticket;
        std::wstring text;
        bool accepted;
        HANDLE done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        HRESULT result = E_ABORT;
        Update(ULONGLONG ticket, PCWSTR text, bool accepted) : ticket(ticket), text(text), accepted(accepted) {}
        ~Update() { if (done) CloseHandle(done); }
    };
    std::deque<std::shared_ptr<Update>> updates;
    static constexpr UINT ScanMessage = WM_APP + 17;
    ULONGLONG acceptedAt = 0;
    void Clear()
    {
        std::lock_guard<std::mutex> lock(gate);
        ++generation; Erase(password); acceptedAt = 0; scanning = false;
        for (auto& update : updates) SetEvent(update->done);
        updates.clear();
    }
    ULONGLONG Begin()
    {
        std::lock_guard<std::mutex> lock(gate);
        Erase(password); acceptedAt = 0;
        scanning = true;
        detail = L"Viso could not complete the scan. Try again or use another sign-in option.";
        return ++generation;
    }
    HRESULT Scan(ULONGLONG ticket, IQueryContinueWithStatus* query, const std::function<HRESULT(PCWSTR)>& status)
    {
        try {
            if (FAILED(status(L"Starting Viso. Look at the camera with both eyes open."))) return HRESULT_FROM_WIN32(ERROR_CANCELLED);
            Pipe pipe(query, [&] { return generation.load() == ticket; }); pipe.Send({L"verify", sid, kind, qualified});
            while (true) {
                auto response = pipe.Receive();
                if (response[0] == L"credential" && response.size() == 4 && response[1] == kind && _wcsicmp(response[2].c_str(), qualified.c_str()) == 0 && !response[3].empty() && response[3].size() <= 256) {
                    if (query && query->QueryContinue() != S_OK) return HRESULT_FROM_WIN32(ERROR_CANCELLED);
                    std::lock_guard<std::mutex> lock(gate);
                    if (generation.load() != ticket) return HRESULT_FROM_WIN32(ERROR_CANCELLED);
                    password = response[3]; acceptedAt = GetTickCount64(); scanning = false; return S_OK;
                }
                if (response[0] == L"error" && response.size() == 2) {
                    std::lock_guard<std::mutex> lock(gate);
                    if (generation.load() == ticket) { detail = response[1]; scanning = false; }
                    return S_FALSE;
                }
                if ((response[0] != L"prompt" && response[0] != L"status") || response.size() != 2) throw std::runtime_error("response");
                if (generation.load() != ticket || FAILED(status(response[1].c_str())) || (query && query->QueryContinue() != S_OK)) return HRESULT_FROM_WIN32(ERROR_CANCELLED);
                pipe.Send({L"ack"});
            }
        } catch (...) {
            std::lock_guard<std::mutex> lock(gate);
            if (generation.load() == ticket) { Erase(password); acceptedAt = 0; scanning = false; }
            return S_FALSE;
        }
    }
    HRESULT Publish(ULONGLONG ticket, PCWSTR text, bool accepted = false)
    {
        auto update = std::make_shared<Update>(ticket, text, accepted);
        if (!update->done) return E_OUTOFMEMORY;
        {
            std::lock_guard<std::mutex> lock(gate);
            if (generation.load() != ticket || !scanWindow) return E_ABORT;
            updates.push_back(update);
            if (!PostMessageW(scanWindow, ScanMessage, 0, 0)) { updates.pop_back(); return E_ABORT; }
        }
        auto deadline = GetTickCount64() + 5000;
        while (generation.load() == ticket && GetTickCount64() < deadline) {
            if (WaitForSingleObject(update->done, 100) == WAIT_OBJECT_0) return update->result;
        }
        return E_ABORT;
    }
    void PresentUpdates()
    {
        // All LogonUI COM callbacks run on the apartment that advised us.
        // These interfaces have no system-registered cross-apartment proxies.
        while (true) {
            std::shared_ptr<Update> update;
            {
                std::lock_guard<std::mutex> lock(gate);
                if (updates.empty()) return;
                update = updates.front(); updates.pop_front();
            }
            if (generation.load() == update->ticket) {
                if (update->accepted) {
                    if (providerEvents && HasCredential()) update->result = providerEvents->CredentialsChanged(context);
                } else if (events) update->result = events->SetFieldString(static_cast<ICredentialProviderCredential2*>(this), 2, update->text.c_str());
            }
            SetEvent(update->done);
        }
    }
    static LRESULT CALLBACK ScanWindowProc(HWND window, UINT message, WPARAM wparam, LPARAM lparam, UINT_PTR id, DWORD_PTR data)
    {
        if (message == ScanMessage) {
            auto owner = reinterpret_cast<Credential*>(data);
            owner->AddRef(); owner->PresentUpdates(); owner->Release(); return 0;
        }
        if (message == WM_NCDESTROY) RemoveWindowSubclass(window, ScanWindowProc, id);
        return DefSubclassProc(window, message, wparam, lparam);
    }
    void StartSelected()
    {
        // A message-only window keeps callbacks on LogonUI's thread. No camera,
        // pipe connection, inference, or wait occurs in SetSelected.
        if (!selected || attempted || !events || !providerEvents) return;
        attempted = true;
        if (!scanWindow) {
            HWND window = CreateWindowExW(0, L"STATIC", L"", 0, 0, 0, 0, 0, HWND_MESSAGE, nullptr, nullptr, nullptr);
            if (!window) return;
            if (!SetWindowSubclass(window, ScanWindowProc, 1, reinterpret_cast<DWORD_PTR>(this))) { DestroyWindow(window); return; }
            std::lock_guard<std::mutex> lock(gate);
            scanWindow = window;
        }
        auto ticket = Begin();
        AddRef();
        try {
            std::thread([this, ticket] {
                try {
                    HRESULT hr = Scan(ticket, nullptr, [&](PCWSTR text) { return Publish(ticket, text); });
                    if (generation.load() == ticket) {
                        if (hr == S_OK && HasCredential()) Publish(ticket, L"", true);
                        else {
                            std::wstring message;
                            { std::lock_guard<std::mutex> lock(gate); message = detail + L" Select the arrow to retry."; }
                            Publish(ticket, message.c_str());
                        }
                    }
                } catch (...) { }
                { std::lock_guard<std::mutex> lock(gate); if (generation.load() == ticket) scanning = false; }
                Release();
            }).detach();
        } catch (...) { Clear(); Release(); }
    }
    void CloseScanWindow()
    {
        HWND window;
        { std::lock_guard<std::mutex> lock(gate); window = scanWindow; scanWindow = nullptr; }
        if (window) DestroyWindow(window);
    }
public:
    Credential(std::wstring sid, std::wstring qualified, bool local, CREDENTIAL_PROVIDER_USAGE_SCENARIO scenario)
        : sid(std::move(sid)), qualified(std::move(qualified)), kind(local ? L"local" : L"microsoft"), scenario(scenario) { ++objects; }
    ~Credential() { Clear(); --objects; }
    bool HasCredential() { std::lock_guard<std::mutex> lock(gate); return !password.empty() && acceptedAt && GetTickCount64() - acceptedAt <= 10000; }
    bool Linked() const
    {
        wchar_t data[MAX_PATH];
        if (FAILED(SHGetFolderPathW(nullptr, CSIDL_COMMON_APPDATA, nullptr, SHGFP_TYPE_CURRENT, data))) return false;
        auto path = std::wstring(data) + L"\\Viso\\Accounts\\" + sid + L".dpapi";
        DWORD attributes = GetFileAttributesW(path.c_str());
        return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT));
    }
    void SetProviderEvents(ICredentialProviderEvents* value, UINT_PTR valueContext)
    {
        if (providerEvents) providerEvents->Release();
        providerEvents = value; context = valueContext;
        if (providerEvents) { providerEvents->AddRef(); StartSelected(); }
        else Clear();
    }
    void Detach() { SetDeselected(); UnAdvise(); SetProviderEvents(nullptr, 0); }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** value) override
    {
        if (!value) return E_POINTER; *value = nullptr;
        if (iid == IID_IUnknown || iid == IID_ICredentialProviderCredential || iid == IID_ICredentialProviderCredential2) *value = static_cast<ICredentialProviderCredential2*>(this);
        else if (iid == IID_IConnectableCredentialProviderCredential) *value = static_cast<IConnectableCredentialProviderCredential*>(this);
        else return E_NOINTERFACE;
        AddRef(); return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { ULONG count = --refs; if (!count) delete this; return count; }
    HRESULT STDMETHODCALLTYPE Advise(ICredentialProviderCredentialEvents* value) override { if (events) events->Release(); events = value; if (events) events->AddRef(); StartSelected(); return S_OK; }
    HRESULT STDMETHODCALLTYPE UnAdvise() override { Clear(); CloseScanWindow(); if (events) events->Release(); events = nullptr; return S_OK; }
    HRESULT STDMETHODCALLTYPE SetSelected(BOOL* automatic) override
    {
        if (!automatic) return E_POINTER;
        selected = true; *automatic = HasCredential() ? TRUE : FALSE;
        if (!*automatic) StartSelected();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE SetDeselected() override { selected = attempted = false; Clear(); return S_OK; }
    HRESULT STDMETHODCALLTYPE GetUserSid(PWSTR* result) override { return Copy(sid, result); }
    HRESULT STDMETHODCALLTYPE GetFieldState(DWORD id, CREDENTIAL_PROVIDER_FIELD_STATE* state, CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE* interactive) override
    {
        if (id >= 4 || !state || !interactive) return E_INVALIDARG;
        *state = CPFS_DISPLAY_IN_SELECTED_TILE; *interactive = CPFIS_NONE; return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetStringValue(DWORD id, PWSTR* value) override
    {
        if (!value) return E_POINTER; *value = nullptr;
        if (id == 1) return Copy(L"Viso Face", value);
        if (id == 2) { std::lock_guard<std::mutex> lock(gate); return Copy(detail, value); }
        if (id == 3) return Copy(L"Scan and sign in", value);
        return E_INVALIDARG;
    }
    HRESULT STDMETHODCALLTYPE GetBitmapValue(DWORD id, HBITMAP* bitmap) override
    {
        if (!bitmap) return E_POINTER; *bitmap = nullptr;
        if (id != 0) return E_INVALIDARG;
        BITMAPINFO info = {}; info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER); info.bmiHeader.biWidth = 64; info.bmiHeader.biHeight = -64;
        info.bmiHeader.biPlanes = 1; info.bmiHeader.biBitCount = 32; info.bmiHeader.biCompression = BI_RGB;
        DWORD* pixels = nullptr; *bitmap = CreateDIBSection(nullptr, &info, DIB_RGB_COLORS, reinterpret_cast<void**>(&pixels), nullptr, 0);
        if (!*bitmap) return E_OUTOFMEMORY;
        for (int y = 0; y < 64; ++y) for (int x = 0; x < 64; ++x) {
            int dx = x - 32, dy = y - 32, r = dx * dx + dy * dy;
            bool ring = r > 650 && r < 810;
            bool eye = y > 23 && y < 30 && ((x > 22 && x < 26) || (x > 38 && x < 42));
            bool smile = y > 37 && y < 44 && r < 150 && r > 85;
            pixels[y * 64 + x] = ring || eye || smile ? 0xff3499ff : 0xff141619;
        }
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetSubmitButtonValue(DWORD id, DWORD* adjacent) override { if (id != 3 || !adjacent) return E_INVALIDARG; *adjacent = 2; return S_OK; }
    HRESULT STDMETHODCALLTYPE GetCheckboxValue(DWORD, BOOL*, PWSTR*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetComboBoxValueCount(DWORD, DWORD*, DWORD*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE GetComboBoxValueAt(DWORD, DWORD, PWSTR*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE SetStringValue(DWORD, PCWSTR) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE SetCheckboxValue(DWORD, BOOL) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE SetComboBoxSelectedValue(DWORD, DWORD) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE CommandLinkClicked(DWORD) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE Connect(IQueryContinueWithStatus* query) override
    {
        if (!query) return E_INVALIDARG;
        if (HasCredential()) return S_OK;
        { std::lock_guard<std::mutex> lock(gate); if (scanning) return S_OK; }
        attempted = true;
        auto ticket = Begin();
        HRESULT hr = Scan(ticket, query, [&](PCWSTR text) { return query->SetStatusMessage(text); });
        { std::lock_guard<std::mutex> lock(gate); if (generation.load() == ticket) scanning = false; }
        return FAILED(hr) ? hr : S_OK;
    }
    HRESULT STDMETHODCALLTYPE Disconnect() override { Clear(); return S_OK; }
    HRESULT STDMETHODCALLTYPE GetSerialization(CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE* response, CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* serialized, PWSTR* text, CREDENTIAL_PROVIDER_STATUS_ICON* icon) override
    {
        if (!response || !serialized || !text || !icon) return E_POINTER;
        std::lock_guard<std::mutex> lock(gate);
        *response = CPGSR_NO_CREDENTIAL_NOT_FINISHED; *serialized = {}; *text = nullptr; *icon = CPSI_NONE;
        if (scanning) return S_OK;
        if (password.empty() || !acceptedAt || GetTickCount64() - acceptedAt > 10000) { Erase(password); acceptedAt = 0; ++generation; *icon = CPSI_ERROR; return Copy(detail, text); }
        HRESULT hr;
        try { hr = PackCredential(kind == L"local", qualified, password, scenario, serialized); }
        catch (...) { hr = E_OUTOFMEMORY; }
        Erase(password); acceptedAt = 0; ++generation;
        if (SUCCEEDED(hr)) *response = CPGSR_RETURN_CREDENTIAL_FINISHED;
        else { *icon = CPSI_ERROR; Copy(L"Windows could not prepare the credential. Use another sign-in option.", text); }
        return hr;
    }
    HRESULT STDMETHODCALLTYPE ReportResult(NTSTATUS status, NTSTATUS, PWSTR* text, CREDENTIAL_PROVIDER_STATUS_ICON* icon) override
    {
        Clear(); if (!text || !icon) return E_POINTER; *text = nullptr; *icon = CPSI_NONE;
        if (status < 0) { *icon = CPSI_ERROR; return Copy(L"Windows rejected the saved credential. Sign in with your password or PIN, then relink this account in Viso Settings.", text); }
        return S_OK;
    }
};

class Provider final : public ICredentialProvider, public ICredentialProviderSetUserArray
{
    std::atomic<ULONG> refs{1};
    CREDENTIAL_PROVIDER_USAGE_SCENARIO scenario = CPUS_INVALID;
    std::vector<Credential*> credentials;
    ICredentialProviderEvents* events = nullptr;
    UINT_PTR context = 0;
    void Clear() { for (auto item : credentials) { item->Detach(); item->Release(); } credentials.clear(); }
public:
    Provider() { ++objects; }
    ~Provider() { Clear(); if (events) events->Release(); --objects; }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** value) override
    {
        if (!value) return E_POINTER; *value = nullptr;
        if (iid == IID_IUnknown || iid == IID_ICredentialProvider) *value = static_cast<ICredentialProvider*>(this);
        else if (iid == IID_ICredentialProviderSetUserArray) *value = static_cast<ICredentialProviderSetUserArray*>(this);
        else return E_NOINTERFACE;
        AddRef(); return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { ULONG count = --refs; if (!count) delete this; return count; }
    HRESULT STDMETHODCALLTYPE SetUsageScenario(CREDENTIAL_PROVIDER_USAGE_SCENARIO value, DWORD) override
    {
        Clear(); scenario = CPUS_INVALID;
        if (value != CPUS_LOGON && value != CPUS_UNLOCK_WORKSTATION) return E_NOTIMPL;
        scenario = value; return S_OK;
    }
    HRESULT STDMETHODCALLTYPE SetSerialization(const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION*) override { return E_NOTIMPL; }
    HRESULT STDMETHODCALLTYPE Advise(ICredentialProviderEvents* value, UINT_PTR valueContext) override
    {
        if (events) events->Release(); events = value; context = valueContext;
        if (events) events->AddRef();
        for (auto item : credentials) item->SetProviderEvents(events, context);
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE UnAdvise() override
    {
        for (auto item : credentials) item->SetProviderEvents(nullptr, 0);
        if (events) events->Release(); events = nullptr; return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetFieldDescriptorCount(DWORD* count) override { if (!count) return E_POINTER; *count = 4; return S_OK; }
    HRESULT STDMETHODCALLTYPE GetFieldDescriptorAt(DWORD id, CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** result) override
    {
        if (!result) return E_POINTER; *result = nullptr; if (id >= 4) return E_INVALIDARG;
        static const CREDENTIAL_PROVIDER_FIELD_TYPE types[] = {CPFT_TILE_IMAGE, CPFT_LARGE_TEXT, CPFT_SMALL_TEXT, CPFT_SUBMIT_BUTTON};
        static const PCWSTR labels[] = {L"Viso Face", L"Viso Face", L"Look at the camera", L"Scan and sign in"};
        auto field = static_cast<CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR*>(CoTaskMemAlloc(sizeof(CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR)));
        if (!field) return E_OUTOFMEMORY;
        *field = {}; field->dwFieldID = id; field->cpft = types[id];
        if (id == 0) field->guidFieldType = CPFG_CREDENTIAL_PROVIDER_LOGO;
        if (id == 1) field->guidFieldType = CPFG_CREDENTIAL_PROVIDER_LABEL;
        HRESULT hr = SHStrDupW(labels[id], &field->pszLabel);
        if (FAILED(hr)) CoTaskMemFree(field); else *result = field;
        return hr;
    }
    HRESULT STDMETHODCALLTYPE GetCredentialCount(DWORD* count, DWORD* defaultIndex, BOOL* automatic) override
    {
        if (!count || !defaultIndex || !automatic) return E_POINTER;
        *count = static_cast<DWORD>(credentials.size()); *defaultIndex = CREDENTIAL_PROVIDER_NO_DEFAULT; *automatic = FALSE;
        for (DWORD i = 0; i < *count; ++i) {
            if (credentials[i]->HasCredential()) { *defaultIndex = i; *automatic = TRUE; return S_OK; }
            if (*defaultIndex == CREDENTIAL_PROVIDER_NO_DEFAULT && credentials[i]->Linked()) *defaultIndex = i;
        }
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetCredentialAt(DWORD index, ICredentialProviderCredential** value) override
    {
        if (!value) return E_POINTER; *value = nullptr; if (index >= credentials.size()) return E_INVALIDARG;
        return credentials[index]->QueryInterface(IID_ICredentialProviderCredential, reinterpret_cast<void**>(value));
    }
    HRESULT STDMETHODCALLTYPE SetUserArray(ICredentialProviderUserArray* users) override
    {
        Clear(); if (!users || scenario == CPUS_INVALID) return E_INVALIDARG;
        DWORD count = 0; HRESULT hr = users->GetCount(&count); if (FAILED(hr)) return hr;
        wchar_t computer[MAX_COMPUTERNAME_LENGTH + 1]; DWORD length = ARRAYSIZE(computer); if (!GetComputerNameW(computer, &length)) return E_FAIL;
        std::wstring localPrefix = std::wstring(computer) + L"\\";
        try {
            for (DWORD i = 0; i < count && i < 128; ++i) {
                ICredentialProviderUser* user = nullptr;
                if (FAILED(users->GetAt(i, &user))) continue;
                PWSTR sid = nullptr, qualified = nullptr; GUID provider = {};
                hr = user->GetSid(&sid);
                if (SUCCEEDED(hr)) hr = user->GetStringValue(PKEY_Identity_QualifiedUserName, &qualified);
                if (SUCCEEDED(hr)) hr = user->GetProviderID(&provider);
                user->Release();
                if (SUCCEEDED(hr) && sid && qualified) {
                    bool local = provider == Identity_LocalUserProvider && _wcsnicmp(qualified, localPrefix.c_str(), localPrefix.size()) == 0;
                    bool microsoft = _wcsnicmp(qualified, L"MicrosoftAccount\\", 17) == 0;
                    if (local || microsoft) {
                        auto credential = new (std::nothrow) Credential(sid, qualified, local, scenario);
                        if (credential) { credential->SetProviderEvents(events, context); credentials.push_back(credential); }
                    }
                }
                CoTaskMemFree(sid); CoTaskMemFree(qualified);
            }
        } catch (...) { Clear(); return E_OUTOFMEMORY; }
        return S_OK;
    }
};

class Factory final : public IClassFactory
{
    std::atomic<ULONG> refs{1};
public:
    Factory() { ++objects; } ~Factory() { --objects; }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** value) override { if (!value) return E_POINTER; *value = nullptr; if (iid != IID_IUnknown && iid != IID_IClassFactory) return E_NOINTERFACE; *value = this; AddRef(); return S_OK; }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs; }
    ULONG STDMETHODCALLTYPE Release() override { ULONG count = --refs; if (!count) delete this; return count; }
    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown* outer, REFIID iid, void** value) override
    {
        if (!value) return E_POINTER; *value = nullptr; if (outer) return CLASS_E_NOAGGREGATION;
        auto provider = new (std::nothrow) Provider(); if (!provider) return E_OUTOFMEMORY;
        HRESULT hr = provider->QueryInterface(iid, value); provider->Release(); return hr;
    }
    HRESULT STDMETHODCALLTYPE LockServer(BOOL locked) override { if (locked) ++objects; else --objects; return S_OK; }
};

STDAPI DllGetClassObject(REFCLSID clsid, REFIID iid, void** value)
{
    if (!value) return E_POINTER; *value = nullptr; if (clsid != CLSID_Viso) return CLASS_E_CLASSNOTAVAILABLE;
    auto factory = new (std::nothrow) Factory(); if (!factory) return E_OUTOFMEMORY;
    HRESULT hr = factory->QueryInterface(iid, value); factory->Release(); return hr;
}
STDAPI DllCanUnloadNow() { return objects == 0 ? S_OK : S_FALSE; }
