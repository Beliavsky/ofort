#include "ofort.h"
#include "ofort_build_version.h"

const char *ofort_web_build_info(void) {
    return "ofort " OFORT_VERSION " / " OFORT_BUILD_COMMIT
           " / built " __DATE__ " " __TIME__ " / Emscripten";
}
