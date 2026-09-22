// Content sniffing for extracted asset payloads.
//
// Publisher hands images over with a declared MIME type, but the
// declaration comes from a file written by a twenty-year-old application
// and is not always right. Everything here reads only the payload's own
// header bytes: no decoding, no allocation driven by the file's own
// numbers, and no attempt to repair anything.
#ifndef PUBIR_IMAGE_INFO_H
#define PUBIR_IMAGE_INFO_H

#include <cstddef>
#include <string>

namespace pubir {

struct ImageInfo {
  // Sniffed from the payload; empty when nothing matched.
  std::string sniffedMime;
  bool hasDimensions = false;
  long long pixelWidth = 0;
  long long pixelHeight = 0;
};

// Reads magic bytes and, where the format puts them at a fixed offset,
// pixel dimensions. Formats whose dimensions need real decoding (WMF, EMF,
// progressive oddities) return hasDimensions = false rather than a guess.
ImageInfo sniffImage(const unsigned char *data, std::size_t len);

// Filename extension for a MIME type, without the dot. Unknown types get
// "bin" so an unrecognised payload still lands on disk under a safe name.
std::string extensionForMime(const std::string &mime);

// Lowercases and strips any ";charset=..." parameter.
std::string normaliseMime(const std::string &mime);

// True for raster formats the renderer could hand to Google directly.
bool isRasterMime(const std::string &mime);

// True for metafile formats that would need rasterising first.
bool isMetafileMime(const std::string &mime);

} // namespace pubir

#endif
