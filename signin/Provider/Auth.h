#pragma once
#include <windows.h>
#include <credentialprovider.h>
#include <string>

inline constexpr GUID CLSID_Viso = {0x4965c343,0x8550,0x499a,{0xa7,0x34,0x51,0x28,0x63,0x66,0x8d,0x12}};
inline void Erase(std::wstring& value) { if (!value.empty()) SecureZeroMemory(value.data(), value.size() * sizeof(wchar_t)); value.clear(); }
HRESULT PackCredential(bool local, const std::wstring& qualified, const std::wstring& password,
    CREDENTIAL_PROVIDER_USAGE_SCENARIO scenario, CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* result);
