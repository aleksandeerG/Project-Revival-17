// Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
#include "common.h"

#include <winhttp.h>
#include <wincrypt.h>
#include <cstdio>

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "crypt32.lib")

namespace revival {

namespace {

std::wstring widen(const std::string& value) {
    if (value.empty()) return L"";
    int needed = MultiByteToWideChar(CP_UTF8, 0, value.data(), (int)value.size(), nullptr, 0);
    std::wstring wide(needed, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, value.data(), (int)value.size(), wide.data(), needed);
    return wide;
}

std::string json_escape(const std::string& value) {
    std::string escaped;
    escaped.reserve(value.size());
    constexpr char hex[] = "0123456789abcdef";
    for (unsigned char c : value) {
        switch (c) {
            case '"': escaped += "\\\""; break;
            case '\\': escaped += "\\\\"; break;
            case '\b': escaped += "\\b"; break;
            case '\f': escaped += "\\f"; break;
            case '\n': escaped += "\\n"; break;
            case '\r': escaped += "\\r"; break;
            case '\t': escaped += "\\t"; break;
            default:
                if (c < 0x20) {
                    escaped += "\\u00";
                    escaped.push_back(hex[c >> 4]);
                    escaped.push_back(hex[c & 0x0f]);
                } else {
                    escaped.push_back(static_cast<char>(c));
                }
        }
    }
    return escaped;
}

std::string json_field(const std::string& body, const std::string& key) {
    std::string needle = "\"" + key + "\"";
    size_t pos = body.find(needle);
    if (pos == std::string::npos) return "";
    pos = body.find(':', pos + needle.size());
    if (pos == std::string::npos) return "";
    pos++;
    while (pos < body.size() && (body[pos] == ' ' || body[pos] == '\t')) pos++;
    if (pos >= body.size()) return "";
    if (body[pos] == '"') {
        size_t end = body.find('"', pos + 1);
        if (end == std::string::npos) return "";
        return body.substr(pos + 1, end - pos - 1);
    }
    size_t end = body.find_first_of(",}", pos);
    if (end == std::string::npos) end = body.size();
    std::string value = body.substr(pos, end - pos);
    while (!value.empty() && (value.back() == ' ' || value.back() == '\r' || value.back() == '\n'))
        value.pop_back();
    return value;
}

struct HttpResponse {
    bool ok = false;
    DWORD status = 0;
    std::string body;
    std::string error;
};

bool decode_pin(const std::string& text, BYTE expected[32]) {
    std::string compact;
    for (char c : text) if (c != ':' && c != ' ' && c != '\t') compact.push_back(c);
    if (compact.size() != 64) return false;
    auto nibble = [](char c) -> int {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    };
    for (size_t i = 0; i < 32; ++i) {
        int high = nibble(compact[i * 2]), low = nibble(compact[i * 2 + 1]);
        if (high < 0 || low < 0) return false;
        expected[i] = static_cast<BYTE>((high << 4) | low);
    }
    return true;
}

bool certificate_matches_pin(HINTERNET request, const std::string& pin) {
    BYTE expected[32] = {};
    if (!decode_pin(pin, expected)) return false;

    PCCERT_CONTEXT certificate = nullptr;
    DWORD size = sizeof(certificate);
    if (!WinHttpQueryOption(request, WINHTTP_OPTION_SERVER_CERT_CONTEXT,
                            &certificate, &size) || certificate == nullptr) return false;

    BYTE actual[32] = {};
    DWORD actual_size = sizeof(actual);
    BOOL hashed = CryptHashCertificate2(
        L"SHA256", 0, nullptr, certificate->pbCertEncoded,
        certificate->cbCertEncoded, actual, &actual_size);
    CertFreeCertificateContext(certificate);
    if (!hashed || actual_size != sizeof(actual)) return false;

    BYTE difference = 0;
    for (size_t i = 0; i < sizeof(actual); ++i) difference |= actual[i] ^ expected[i];
    return difference == 0;
}

HttpResponse request(const std::wstring& host, int port, const std::wstring& method,
                     const std::wstring& path, const std::string& body,
                     const std::wstring& extra_headers, const std::string& certificate_pin) {
    HttpResponse out;
    HINTERNET session = WinHttpOpen(L"FIFA17Revival/0.1", WINHTTP_ACCESS_TYPE_NO_PROXY,
                                    WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) { out.error = "WinHttpOpen failed"; return out; }

    HINTERNET connect = WinHttpConnect(session, host.c_str(), (INTERNET_PORT)port, 0);
    if (!connect) { out.error = "WinHttpConnect failed"; WinHttpCloseHandle(session); return out; }

    HINTERNET req = WinHttpOpenRequest(connect, method.c_str(), path.c_str(), nullptr,
                                       WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
                                       WINHTTP_FLAG_SECURE);
    if (!req) {
        out.error = "WinHttpOpenRequest failed";
        WinHttpCloseHandle(connect); WinHttpCloseHandle(session); return out;
    }

    DWORD security = SECURITY_FLAG_IGNORE_UNKNOWN_CA | SECURITY_FLAG_IGNORE_CERT_CN_INVALID |
                     SECURITY_FLAG_IGNORE_CERT_DATE_INVALID | SECURITY_FLAG_IGNORE_CERT_WRONG_USAGE;
    WinHttpSetOption(req, WINHTTP_OPTION_SECURITY_FLAGS, &security, sizeof(security));

    BOOL sent = WinHttpSendRequest(
        req, extra_headers.empty() ? WINHTTP_NO_ADDITIONAL_HEADERS : extra_headers.c_str(),
        extra_headers.empty() ? 0 : (DWORD)-1L,
        WINHTTP_NO_REQUEST_DATA, 0, (DWORD)body.size(), 0);
    if (!sent) {
        out.error = "send failed (WinHttp error " + std::to_string(GetLastError()) + ")";
        WinHttpCloseHandle(req); WinHttpCloseHandle(connect); WinHttpCloseHandle(session);
        return out;
    }

    if (!certificate_matches_pin(req, certificate_pin)) {
        out.error = "server certificate pin mismatch";
        WinHttpCloseHandle(req); WinHttpCloseHandle(connect); WinHttpCloseHandle(session);
        return out;
    }

    if (!body.empty()) {
        DWORD written = 0;
        if (!WinHttpWriteData(req, body.data(), (DWORD)body.size(), &written) ||
            written != body.size()) {
            out.error = "body send failed (WinHttp error " +
                        std::to_string(GetLastError()) + ")";
            WinHttpCloseHandle(req); WinHttpCloseHandle(connect); WinHttpCloseHandle(session);
            return out;
        }
    }
    if (!WinHttpReceiveResponse(req, nullptr)) {
        out.error = "receive failed (WinHttp error " + std::to_string(GetLastError()) + ")";
        WinHttpCloseHandle(req); WinHttpCloseHandle(connect); WinHttpCloseHandle(session);
        return out;
    }

    DWORD status = 0, status_size = sizeof(status);
    WinHttpQueryHeaders(req, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                        WINHTTP_HEADER_NAME_BY_INDEX, &status, &status_size, WINHTTP_NO_HEADER_INDEX);
    out.status = status;

    DWORD available = 0;
    do {
        available = 0;
        if (!WinHttpQueryDataAvailable(req, &available) || available == 0) break;
        std::string chunk(available, '\0');
        DWORD read = 0;
        if (WinHttpReadData(req, chunk.data(), available, &read) && read > 0) {
            out.body.append(chunk.data(), read);
        }
    } while (available > 0);

    out.ok = true;
    WinHttpCloseHandle(req);
    WinHttpCloseHandle(connect);
    WinHttpCloseHandle(session);
    return out;
}

}

AuthResult accounts_login_and_authorize(const Config& config) {
    AuthResult result;
    const std::wstring host = widen(config.host);

    if (config.username.empty() || config.password.empty()) {
        result.error = "no [Credentials] Username/Password in config";
        log_line("[LOGIN] %s", result.error.c_str());
        return result;
    }

    std::string login_body = "{\"username\":\"" + json_escape(config.username) +
                             "\",\"password\":\"" + json_escape(config.password) + "\"}";
    log_line("[LOGIN] POST https://%s:%d/accounts/login as %s", config.host.c_str(),
             config.login_port, config.username.c_str());
    HttpResponse login = request(host, config.login_port, L"POST", L"/accounts/login", login_body,
                                 L"Content-Type: application/json\r\nConnection: close\r\n",
                                 config.certificate_pin);
    result.status = login.status;
    if (!login.ok) {
        result.error = login.error;
        log_line("[LOGIN] transport error: %s", login.error.c_str());
        return result;
    }
    if (login.status != 200) {
        result.error = "login HTTP " + std::to_string(login.status);
        log_line("[LOGIN] HTTP %lu: %s", login.status, login.body.c_str());
        return result;
    }

    result.sid = json_field(login.body, "sid");
    result.persona_id = json_field(login.body, "nucleusPersonaId");
    result.display_name = json_field(login.body, "nucleusPersonaDisplayName");
    if (result.sid.empty()) {
        result.error = "no sid in login response";
        log_line("[LOGIN] %s: %s", result.error.c_str(), login.body.c_str());
        return result;
    }
    log_line("[LOGIN] session established; personaId=%s (%s)", result.persona_id.c_str(),
             result.display_name.c_str());

    std::string auth_body = "{\"client_id\":\"fifa17\",\"response_type\":\"code\","
                            "\"access_token\":\"" + json_escape(result.sid) + "\"}";
    HttpResponse auth = request(host, config.login_port, L"POST", L"/accounts/connect/auth",
                                auth_body,
                                L"Content-Type: application/json\r\nAccept: */*\r\n",
                                config.certificate_pin);
    if (!auth.ok) {
        result.error = auth.error;
        log_line("[LOGIN] auth-code transport error: %s", auth.error.c_str());
        return result;
    }
    result.auth_code = json_field(auth.body, "code");
    if (result.auth_code.empty()) {
        result.error = "no auth code (HTTP " + std::to_string(auth.status) + ")";
        log_line("[LOGIN] %s: %s", result.error.c_str(), auth.body.c_str());
        return result;
    }

    result.ok = true;
    log_line("[LOGIN] auth code obtained (%.8s...)", result.auth_code.c_str());
    log_line("[LOGIN] auth code ready for the Origin SDK bridge");
    return result;
}

}
