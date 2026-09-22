#include "image_info.h"

#include <cctype>
#include <cstring>

namespace pubir {
namespace {

inline bool startsWith(const unsigned char *d, std::size_t len, const char *sig, std::size_t sigLen) {
  return len >= sigLen && std::memcmp(d, sig, sigLen) == 0;
}

inline long long be32(const unsigned char *p) {
  return (static_cast<long long>(p[0]) << 24) | (static_cast<long long>(p[1]) << 16) |
         (static_cast<long long>(p[2]) << 8) | static_cast<long long>(p[3]);
}

inline long long be16(const unsigned char *p) {
  return (static_cast<long long>(p[0]) << 8) | static_cast<long long>(p[1]);
}

inline long long le16(const unsigned char *p) {
  return (static_cast<long long>(p[1]) << 8) | static_cast<long long>(p[0]);
}

inline long long le32signed(const unsigned char *p) {
  const unsigned long v = (static_cast<unsigned long>(p[3]) << 24) |
                          (static_cast<unsigned long>(p[2]) << 16) |
                          (static_cast<unsigned long>(p[1]) << 8) |
                          static_cast<unsigned long>(p[0]);
  return static_cast<long long>(static_cast<int32_t>(v));
}

bool sniffJpegSize(const unsigned char *d, std::size_t len, ImageInfo &info) {
  // Walk the marker segments to the first frame header. Every step is
  // bounded by `len`, and a malformed length field ends the walk instead
  // of moving the cursor backwards.
  std::size_t i = 2;
  while (i + 3 < len) {
    if (d[i] != 0xFF) {
      i++; // Fill byte or padding; resynchronise rather than give up.
      continue;
    }
    const unsigned char marker = d[i + 1];
    if (marker == 0xFF) { i++; continue; }
    if (marker == 0xD8 || marker == 0x01 || (marker >= 0xD0 && marker <= 0xD7)) {
      i += 2;
      continue;
    }
    if (marker == 0xD9 || marker == 0xDA) return false; // End, or entropy data.
    if (i + 4 > len) return false;
    const long long segLen = be16(d + i + 2);
    if (segLen < 2) return false;
    const bool isFrame = (marker >= 0xC0 && marker <= 0xCF) && marker != 0xC4 && marker != 0xC8 &&
                         marker != 0xCC;
    if (isFrame) {
      // SOFn: [len:2][precision:1][height:2][width:2]
      if (i + 9 > len) return false;
      info.pixelHeight = be16(d + i + 5);
      info.pixelWidth = be16(d + i + 7);
      return info.pixelWidth > 0 && info.pixelHeight > 0;
    }
    i += 2 + static_cast<std::size_t>(segLen);
  }
  return false;
}

} // namespace

ImageInfo sniffImage(const unsigned char *data, std::size_t len) {
  ImageInfo info;
  if (data == nullptr || len < 4) return info;

  if (startsWith(data, len, "\x89PNG\r\n\x1a\n", 8)) {
    info.sniffedMime = "image/png";
    // IHDR is required to be the first chunk: [len:4]["IHDR"][w:4][h:4]
    if (len >= 24 && std::memcmp(data + 12, "IHDR", 4) == 0) {
      info.pixelWidth = be32(data + 16);
      info.pixelHeight = be32(data + 20);
      info.hasDimensions = info.pixelWidth > 0 && info.pixelHeight > 0;
    }
    return info;
  }

  if (len >= 3 && data[0] == 0xFF && data[1] == 0xD8 && data[2] == 0xFF) {
    info.sniffedMime = "image/jpeg";
    info.hasDimensions = sniffJpegSize(data, len, info);
    return info;
  }

  if (startsWith(data, len, "GIF87a", 6) || startsWith(data, len, "GIF89a", 6)) {
    info.sniffedMime = "image/gif";
    if (len >= 10) {
      info.pixelWidth = le16(data + 6);
      info.pixelHeight = le16(data + 8);
      info.hasDimensions = info.pixelWidth > 0 && info.pixelHeight > 0;
    }
    return info;
  }

  if (startsWith(data, len, "BM", 2)) {
    info.sniffedMime = "image/bmp";
    // BITMAPINFOHEADER or later: width/height are signed 32-bit at 18/22.
    // A negative height means a top-down bitmap, so take the magnitude.
    if (len >= 26 && le32signed(data + 14) >= 40) {
      const long long w = le32signed(data + 18);
      const long long h = le32signed(data + 22);
      info.pixelWidth = w < 0 ? -w : w;
      info.pixelHeight = h < 0 ? -h : h;
      info.hasDimensions = info.pixelWidth > 0 && info.pixelHeight > 0;
    }
    return info;
  }

  if (startsWith(data, len, "II*\0", 4) || startsWith(data, len, "MM\0*", 4)) {
    // TIFF dimensions live in IFD tags at a file-relative offset. Reading
    // them means walking attacker-controlled offsets, so report the type
    // and leave the size unknown.
    info.sniffedMime = "image/tiff";
    return info;
  }

  if (len >= 4 && data[0] == 0x01 && data[1] == 0x00 && data[2] == 0x00 && data[3] == 0x00) {
    info.sniffedMime = "image/x-emf";
    return info;
  }

  if (startsWith(data, len, "\xd7\xcd\xc6\x9a", 4)) {
    info.sniffedMime = "image/x-wmf";
    return info;
  }

  if (startsWith(data, len, "<?xml", 5) || startsWith(data, len, "<svg", 4)) {
    info.sniffedMime = "image/svg+xml";
    return info;
  }

  return info;
}

std::string normaliseMime(const std::string &mime) {
  std::string out;
  out.reserve(mime.size());
  for (char c : mime) {
    if (c == ';') break;
    if (c == ' ' || c == '\t') continue;
    out += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  }
  return out;
}

std::string extensionForMime(const std::string &mime) {
  const std::string m = normaliseMime(mime);
  if (m == "image/png") return "png";
  if (m == "image/jpeg" || m == "image/jpg" || m == "image/pjpeg") return "jpg";
  if (m == "image/gif") return "gif";
  if (m == "image/bmp" || m == "image/x-ms-bmp") return "bmp";
  if (m == "image/tiff" || m == "image/x-tiff") return "tiff";
  if (m == "image/x-wmf" || m == "image/wmf" || m == "windows/metafile") return "wmf";
  if (m == "image/x-emf" || m == "image/emf") return "emf";
  if (m == "image/svg+xml") return "svg";
  return "bin";
}

bool isRasterMime(const std::string &mime) {
  const std::string e = extensionForMime(mime);
  return e == "png" || e == "jpg" || e == "gif" || e == "bmp";
}

bool isMetafileMime(const std::string &mime) {
  const std::string e = extensionForMime(mime);
  return e == "wmf" || e == "emf" || e == "svg" || e == "tiff";
}

} // namespace pubir
