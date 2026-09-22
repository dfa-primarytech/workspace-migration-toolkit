#include "json.h"

#include <cmath>
#include <cstdio>

namespace pubir {

Json Json::boolean(bool v) {
  Json j;
  j.kind_ = Kind::Bool;
  j.bool_ = v;
  return j;
}

Json Json::integer(long long v) {
  Json j;
  j.kind_ = Kind::Int;
  j.int_ = v;
  return j;
}

Json Json::number(double v) {
  // A non-finite number has no JSON spelling. Rather than emit `NaN` and
  // produce a bundle no parser will read, degrade to null; callers that
  // care add their own diagnostic.
  if (!std::isfinite(v)) return Json::null();
  Json j;
  j.kind_ = Kind::Double;
  j.double_ = v;
  return j;
}

Json Json::string(std::string v) {
  Json j;
  j.kind_ = Kind::String;
  j.string_ = std::move(v);
  return j;
}

Json Json::array() {
  Json j;
  j.kind_ = Kind::Array;
  return j;
}

Json Json::object() {
  Json j;
  j.kind_ = Kind::Object;
  return j;
}

Json &Json::set(const std::string &key, Json value) {
  if (kind_ != Kind::Object) kind_ = Kind::Object;
  for (auto &item : items_) {
    if (item.first == key) {
      item.second = std::move(value);
      return *this;
    }
  }
  items_.emplace_back(key, std::move(value));
  return *this;
}

Json &Json::push(Json value) {
  if (kind_ != Kind::Array) kind_ = Kind::Array;
  items_.emplace_back(std::string(), std::move(value));
  return *this;
}

std::string Json::formatDouble(double v) {
  if (!std::isfinite(v)) return "null";
  // -0.0 and 0.0 must print the same, or two runs over equivalent input
  // produce different bytes.
  if (v == 0.0) return "0";
  if (v == std::floor(v) && std::fabs(v) < 1e15) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%.0f", v);
    return std::string(buf);
  }
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%.6f", v);
  std::string s(buf);
  std::size_t last = s.find_last_not_of('0');
  if (last != std::string::npos && s[last] == '.') last--;
  s.erase(last + 1);
  if (s == "-0") return "0";
  return s;
}

std::string Json::escape(const std::string &s) {
  std::string out;
  out.reserve(s.size() + 2);
  for (unsigned char c : s) {
    switch (c) {
    case '"': out += "\\\""; break;
    case '\\': out += "\\\\"; break;
    case '\b': out += "\\b"; break;
    case '\f': out += "\\f"; break;
    case '\n': out += "\\n"; break;
    case '\r': out += "\\r"; break;
    case '\t': out += "\\t"; break;
    default:
      if (c < 0x20) {
        char buf[8];
        std::snprintf(buf, sizeof(buf), "\\u%04x", c);
        out += buf;
      } else {
        // Bytes >= 0x80 pass through: librevenge hands us UTF-8 already,
        // and re-encoding here would only risk mangling it.
        out += static_cast<char>(c);
      }
    }
  }
  return out;
}

void Json::dumpTo(std::string &out, int indent, int depth) const {
  const bool pretty = indent > 0;
  const std::string pad = pretty ? std::string((depth + 1) * indent, ' ') : std::string();
  const std::string padEnd = pretty ? std::string(depth * indent, ' ') : std::string();

  switch (kind_) {
  case Kind::Null: out += "null"; return;
  case Kind::Bool: out += bool_ ? "true" : "false"; return;
  case Kind::Int: out += std::to_string(int_); return;
  case Kind::Double: out += formatDouble(double_); return;
  case Kind::String:
    out += '"';
    out += escape(string_);
    out += '"';
    return;
  case Kind::Array:
    if (items_.empty()) { out += "[]"; return; }
    out += '[';
    for (std::size_t i = 0; i < items_.size(); i++) {
      if (i) out += ',';
      if (pretty) { out += '\n'; out += pad; }
      items_[i].second.dumpTo(out, indent, depth + 1);
    }
    if (pretty) { out += '\n'; out += padEnd; }
    out += ']';
    return;
  case Kind::Object:
    if (items_.empty()) { out += "{}"; return; }
    out += '{';
    for (std::size_t i = 0; i < items_.size(); i++) {
      if (i) out += ',';
      if (pretty) { out += '\n'; out += pad; }
      out += '"';
      out += escape(items_[i].first);
      out += pretty ? "\": " : "\":";
      items_[i].second.dumpTo(out, indent, depth + 1);
    }
    if (pretty) { out += '\n'; out += padEnd; }
    out += '}';
    return;
  }
}

std::string Json::dump(int indent) const {
  std::string out;
  dumpTo(out, indent, 0);
  if (indent > 0) out += '\n';
  return out;
}

} // namespace pubir
