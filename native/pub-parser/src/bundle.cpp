#include "bundle.h"

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <dirent.h>
#include <fstream>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#include <vector>

#include "serialise.h"

namespace pubir {
namespace {

bool directoryExists(const std::string &path) {
  struct stat st;
  if (::stat(path.c_str(), &st) != 0) return false;
  return S_ISDIR(st.st_mode);
}

bool pathExists(const std::string &path) {
  struct stat st;
  return ::stat(path.c_str(), &st) == 0;
}

bool directoryIsEmpty(const std::string &path) {
  DIR *dir = ::opendir(path.c_str());
  if (dir == nullptr) return false;
  bool empty = true;
  while (struct dirent *entry = ::readdir(dir)) {
    const std::string name(entry->d_name);
    if (name == "." || name == "..") continue;
    empty = false;
    break;
  }
  ::closedir(dir);
  return empty;
}

bool makeDirectory(const std::string &path) {
  if (directoryExists(path)) return true;
  // 0700: the bundle can contain every picture in the source document, so
  // it is not world-readable even on a shared machine.
  return ::mkdir(path.c_str(), 0700) == 0;
}

class ScratchFiles {
public:
  ~ScratchFiles() {
    for (const std::string &path : paths_) ::unlink(path.c_str());
  }
  void track(const std::string &path) { paths_.push_back(path); }
  void released(const std::string &path) {
    for (auto it = paths_.begin(); it != paths_.end(); ++it) {
      if (*it == path) {
        paths_.erase(it);
        return;
      }
    }
  }

private:
  std::vector<std::string> paths_;
};

std::string scratchNameFor(const std::string &finalPath) {
  return finalPath + ".tmp-" + std::to_string(static_cast<long>(::getpid()));
}

bool writeFileAtomic(const std::string &finalPath, const std::string &content, ScratchFiles &scratch,
                     std::string &error) {
  const std::string tmp = scratchNameFor(finalPath);
  scratch.track(tmp);
  {
    std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
    if (!out) {
      error = "could not open a scratch file for writing";
      return false;
    }
    out.write(content.data(), static_cast<std::streamsize>(content.size()));
    out.flush();
    if (!out) {
      error = "writing the scratch file failed";
      return false;
    }
  }
  if (::chmod(tmp.c_str(), 0600) != 0) {
    error = "could not set permissions on the scratch file";
    return false;
  }
  if (::rename(tmp.c_str(), finalPath.c_str()) != 0) {
    error = std::string("could not move the finished file into place: ") + std::strerror(errno);
    return false;
  }
  scratch.released(tmp);
  return true;
}

} // namespace

WriteResult writeBundle(const Document &doc, const Limits &limits, const std::string &outputDir,
                        const std::string &status, bool force, const std::string &failureCode,
                        const std::string &failureMessage) {
  WriteResult result;
  ScratchFiles scratch;

  if (pathExists(outputDir) && !directoryExists(outputDir)) {
    result.errorCode = "output-not-a-directory";
    result.errorMessage = "the output path exists and is not a directory";
    return result;
  }
  if (!makeDirectory(outputDir)) {
    result.errorCode = "output-not-created";
    result.errorMessage = std::string("could not create the output directory: ") +
                          std::strerror(errno);
    return result;
  }
  if (!directoryIsEmpty(outputDir) && !force) {
    result.errorCode = "output-not-empty";
    result.errorMessage =
        "the output directory already contains files; pass --force to write into it anyway";
    return result;
  }

  const std::string assetDir = outputDir + "/assets";
  if (!doc.assets.empty() && !makeDirectory(assetDir)) {
    result.errorCode = "asset-directory-not-created";
    result.errorMessage = std::string("could not create the assets directory: ") +
                          std::strerror(errno);
    return result;
  }

  for (const Asset &asset : doc.assets) {
    // asset.filename is built from the payload's SHA-256, so it cannot
    // contain a separator or traversal sequence whatever the document said.
    const std::string path = outputDir + "/" + asset.filename;
    std::string error;
    if (!writeFileAtomic(path, asset.data, scratch, error)) {
      result.errorCode = "asset-write-failed";
      result.errorMessage = error;
      return result;
    }
  }

  struct Doc {
    const char *name;
    std::string content;
  };
  const std::vector<Doc> documents = {
      {"document.json", documentJson(doc).dump(2)},
      {"assets.json", assetsJson(doc).dump(2)},
      {"report.json", reportJson(doc, limits, status, failureCode, failureMessage).dump(2)},
  };
  for (const Doc &entry : documents) {
    std::string error;
    if (!writeFileAtomic(outputDir + "/" + entry.name, entry.content, scratch, error)) {
      result.errorCode = "bundle-write-failed";
      result.errorMessage = error;
      return result;
    }
  }

  result.ok = true;
  return result;
}

} // namespace pubir
