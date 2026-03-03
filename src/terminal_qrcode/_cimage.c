#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdlib.h>
#include <stdint.h>
#include <string.h>

static int
channels_from_mode(const char *mode)
{
    if (strcmp(mode, "L") == 0) {
        return 1;
    }
    if (strcmp(mode, "RGB") == 0) {
        return 3;
    }
    if (strcmp(mode, "RGBA") == 0) {
        return 4;
    }
    return -1;
}

static uint16_t
read_u16_le(const uint8_t *p)
{
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint32_t
read_u32_le(const uint8_t *p)
{
    return (uint32_t)p[0]
        | ((uint32_t)p[1] << 8)
        | ((uint32_t)p[2] << 16)
        | ((uint32_t)p[3] << 24);
}

static uint32_t
read_u32_be(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24)
        | ((uint32_t)p[1] << 16)
        | ((uint32_t)p[2] << 8)
        | (uint32_t)p[3];
}

static int32_t
read_i32_le(const uint8_t *p)
{
    return (int32_t)read_u32_le(p);
}

static void
write_u32_be(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)((v >> 24) & 0xFF);
    p[1] = (uint8_t)((v >> 16) & 0xFF);
    p[2] = (uint8_t)((v >> 8) & 0xFF);
    p[3] = (uint8_t)(v & 0xFF);
}

static uint32_t
png_crc32(const uint8_t *data, Py_ssize_t len)
{
    uint32_t crc = 0xFFFFFFFFU;
    Py_ssize_t i;
    int j;
    for (i = 0; i < len; i++) {
        crc ^= (uint32_t)data[i];
        for (j = 0; j < 8; j++) {
            if (crc & 1U) {
                crc = (crc >> 1) ^ 0xEDB88320U;
            } else {
                crc >>= 1;
            }
        }
    }
    return crc ^ 0xFFFFFFFFU;
}

static int
paeth_predictor(int a, int b, int c)
{
    int p = a + b - c;
    int pa = p > a ? p - a : a - p;
    int pb = p > b ? p - b : b - p;
    int pc = p > c ? p - c : c - p;
    if (pa <= pb && pa <= pc) {
        return a;
    }
    if (pb <= pc) {
        return b;
    }
    return c;
}

static void
expand_packed_grayscale_row(const uint8_t *row, int width, int bit_depth, uint8_t *out_row)
{
    int x;
    int max_sample = (1 << bit_depth) - 1;
    uint8_t mask = (uint8_t)max_sample;

    for (x = 0; x < width; x++) {
        int bit_pos = x * bit_depth;
        int byte_idx = bit_pos / 8;
        int shift = 8 - bit_depth - (bit_pos % 8);
        uint8_t sample = (uint8_t)((row[byte_idx] >> shift) & mask);
        out_row[x] = (uint8_t)((sample * 255) / max_sample);
    }
}

static int
mode_to_rgb(const uint8_t *src, const char *mode, uint8_t *r, uint8_t *g, uint8_t *b)
{
    if (strcmp(mode, "L") == 0) {
        *r = src[0];
        *g = src[0];
        *b = src[0];
        return 0;
    }
    if (strcmp(mode, "RGB") == 0 || strcmp(mode, "RGBA") == 0) {
        *r = src[0];
        *g = src[1];
        *b = src[2];
        return 0;
    }
    return -1;
}

static PyObject *
cimage_convert(PyObject *self, PyObject *args)
{
    const char *src_mode;
    const char *dst_mode;
    int width;
    int height;
    Py_buffer in_buf;
    int src_channels;
    int dst_channels;
    PyObject *out;
    uint8_t *dst;
    const uint8_t *src;
    Py_ssize_t pixels;
    Py_ssize_t i;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*ssii", &in_buf, &src_mode, &dst_mode, &width, &height)) {
        return NULL;
    }

    src_channels = channels_from_mode(src_mode);
    dst_channels = channels_from_mode(dst_mode);
    if (src_channels < 0 || dst_channels < 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Unsupported mode.");
        return NULL;
    }

    if (width <= 0 || height <= 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid image size.");
        return NULL;
    }

    pixels = (Py_ssize_t)width * (Py_ssize_t)height;
    if (in_buf.len != pixels * src_channels) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Raw data length mismatch.");
        return NULL;
    }

    out = PyBytes_FromStringAndSize(NULL, pixels * dst_channels);
    if (out == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }

    src = (const uint8_t *)in_buf.buf;
    dst = (uint8_t *)PyBytes_AS_STRING(out);

    for (i = 0; i < pixels; i++) {
        uint8_t r, g, b;
        const uint8_t *sp = src + i * src_channels;
        uint8_t *dp = dst + i * dst_channels;
        if (mode_to_rgb(sp, src_mode, &r, &g, &b) != 0) {
            Py_DECREF(out);
            PyBuffer_Release(&in_buf);
            PyErr_SetString(PyExc_ValueError, "Unsupported mode.");
            return NULL;
        }

        if (dst_channels == 1) {
            dp[0] = (uint8_t)((299 * r + 587 * g + 114 * b) / 1000);
        } else if (dst_channels == 3) {
            dp[0] = r;
            dp[1] = g;
            dp[2] = b;
        } else {
            dp[0] = r;
            dp[1] = g;
            dp[2] = b;
            dp[3] = 255;
        }
    }

    PyBuffer_Release(&in_buf);
    return out;
}

static PyObject *
cimage_getbbox_nonwhite(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    const char *mode;
    int width;
    int height;
    int channels;
    const uint8_t *data;
    int left, top, right, bottom;
    int y, x;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*sii", &in_buf, &mode, &width, &height)) {
        return NULL;
    }

    channels = channels_from_mode(mode);
    if (channels < 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Unsupported mode.");
        return NULL;
    }
    if (width <= 0 || height <= 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid image size.");
        return NULL;
    }
    if (in_buf.len != (Py_ssize_t)width * height * channels) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Raw data length mismatch.");
        return NULL;
    }

    data = (const uint8_t *)in_buf.buf;
    left = width;
    top = height;
    right = -1;
    bottom = -1;

    for (y = 0; y < height; y++) {
        int row_start = y * width * channels;
        int row_has = 0;
        for (x = 0; x < width; x++) {
            int idx = row_start + x * channels;
            int nonwhite = (data[idx] < 255);
            if (!nonwhite && channels >= 3) {
                nonwhite = (data[idx + 1] < 255) || (data[idx + 2] < 255);
            }
            if (!nonwhite && channels == 4) {
                nonwhite = (data[idx + 3] < 255);
            }
            if (nonwhite) {
                if (x < left) {
                    left = x;
                }
                if (x > right) {
                    right = x;
                }
                row_has = 1;
            }
        }
        if (row_has) {
            if (y < top) {
                top = y;
            }
            bottom = y;
        }
    }

    PyBuffer_Release(&in_buf);

    if (right < 0) {
        Py_RETURN_NONE;
    }

    return Py_BuildValue("(iiii)", left, top, right + 1, bottom + 1);
}

static PyObject *
cimage_resize_nearest(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    const char *mode;
    int src_w, src_h, dst_w, dst_h;
    int channels;
    PyObject *out;
    const uint8_t *src;
    uint8_t *dst;
    int y, x;

    (void)self;

    if (!PyArg_ParseTuple(
            args,
            "y*siiii",
            &in_buf,
            &mode,
            &src_w,
            &src_h,
            &dst_w,
            &dst_h
        )) {
        return NULL;
    }

    channels = channels_from_mode(mode);
    if (channels < 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Unsupported mode.");
        return NULL;
    }
    if (src_w <= 0 || src_h <= 0 || dst_w <= 0 || dst_h <= 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid image size.");
        return NULL;
    }
    if (in_buf.len != (Py_ssize_t)src_w * src_h * channels) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Raw data length mismatch.");
        return NULL;
    }

    out = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)dst_w * dst_h * channels);
    if (out == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }

    src = (const uint8_t *)in_buf.buf;
    dst = (uint8_t *)PyBytes_AS_STRING(out);

    for (y = 0; y < dst_h; y++) {
        int sy = (y * src_h) / dst_h;
        if (sy >= src_h) {
            sy = src_h - 1;
        }
        for (x = 0; x < dst_w; x++) {
            int sx = (x * src_w) / dst_w;
            int src_idx;
            int dst_idx;
            if (sx >= src_w) {
                sx = src_w - 1;
            }
            src_idx = (sy * src_w + sx) * channels;
            dst_idx = (y * dst_w + x) * channels;
            memcpy(dst + dst_idx, src + src_idx, (size_t)channels);
        }
    }

    PyBuffer_Release(&in_buf);
    return out;
}

static PyObject *
build_decode_result(const char *mode, int width, int height, PyObject *pixels)
{
    PyObject *mode_obj = PyUnicode_FromString(mode);
    PyObject *width_obj = PyLong_FromLong(width);
    PyObject *height_obj = PyLong_FromLong(height);
    PyObject *result;

    if (mode_obj == NULL || width_obj == NULL || height_obj == NULL) {
        Py_XDECREF(mode_obj);
        Py_XDECREF(width_obj);
        Py_XDECREF(height_obj);
        Py_DECREF(pixels);
        return NULL;
    }
    result = PyTuple_New(4);
    if (result == NULL) {
        Py_DECREF(mode_obj);
        Py_DECREF(width_obj);
        Py_DECREF(height_obj);
        Py_DECREF(pixels);
        return NULL;
    }
    PyTuple_SET_ITEM(result, 0, mode_obj);
    PyTuple_SET_ITEM(result, 1, width_obj);
    PyTuple_SET_ITEM(result, 2, height_obj);
    PyTuple_SET_ITEM(result, 3, pixels);
    return result;
}

static PyObject *
cimage_decode_png_8bit(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    const uint8_t *data;
    Py_ssize_t len;
    Py_ssize_t idx;
    int width = 0;
    int height = 0;
    int bit_depth = 0;
    int color_type = 0;
    int compression = 0;
    int flt = 0;
    int interlace = 0;
    int channels = 0;
    int grayscale_packed = 0;
    PyObject *idat = NULL;
    Py_ssize_t idat_len = 0;
    uint8_t *idat_ptr = NULL;
    PyObject *zlib_mod = NULL;
    PyObject *raw_obj = NULL;
    const uint8_t *raw;
    Py_ssize_t raw_len;
    Py_ssize_t expected;
    PyObject *out = NULL;
    uint8_t *out_ptr;
    Py_ssize_t stride;
    uint8_t *prev = NULL;
    uint8_t *row = NULL;
    int y;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*", &in_buf)) {
        return NULL;
    }
    data = (const uint8_t *)in_buf.buf;
    len = in_buf.len;

    if (len < 8 || memcmp(data, "\x89PNG\r\n\x1a\n", 8) != 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Only PNG images are supported.");
        return NULL;
    }

    idx = 8;
    idat = PyBytes_FromStringAndSize(NULL, 0);
    if (idat == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }

    while (1) {
        uint32_t chunk_len;
        const uint8_t *ctype;
        const uint8_t *payload;
        if (idx + 8 > len) {
            Py_DECREF(idat);
            PyBuffer_Release(&in_buf);
            PyErr_SetString(PyExc_ValueError, "Invalid PNG: missing chunk length.");
            return NULL;
        }
        chunk_len = read_u32_be(data + idx);
        idx += 4;
        ctype = data + idx;
        idx += 4;
        if (idx + (Py_ssize_t)chunk_len + 4 > len) {
            Py_DECREF(idat);
            PyBuffer_Release(&in_buf);
            PyErr_SetString(PyExc_ValueError, "Invalid PNG: broken chunk payload.");
            return NULL;
        }
        payload = data + idx;
        idx += chunk_len;
        idx += 4; /* crc */

        if (memcmp(ctype, "IHDR", 4) == 0) {
            if (chunk_len != 13) {
                Py_DECREF(idat);
                PyBuffer_Release(&in_buf);
                PyErr_SetString(PyExc_ValueError, "Invalid PNG: missing IHDR.");
                return NULL;
            }
            width = (int)read_u32_be(payload);
            height = (int)read_u32_be(payload + 4);
            bit_depth = payload[8];
            color_type = payload[9];
            compression = payload[10];
            flt = payload[11];
            interlace = payload[12];
            if (compression != 0 || flt != 0 || interlace != 0) {
                Py_DECREF(idat);
                PyBuffer_Release(&in_buf);
                PyErr_SetString(PyExc_ValueError, "Unsupported PNG compression/filter/interlace.");
                return NULL;
            }
            if (!(color_type == 0 || color_type == 2 || color_type == 6)) {
                Py_DECREF(idat);
                PyBuffer_Release(&in_buf);
                PyErr_SetString(PyExc_ValueError, "Only grayscale/RGB/RGBA PNG is supported.");
                return NULL;
            }
            if (color_type == 0) {
                if (!(bit_depth == 1 || bit_depth == 2 || bit_depth == 4 || bit_depth == 8)) {
                    Py_DECREF(idat);
                    PyBuffer_Release(&in_buf);
                    PyErr_SetString(PyExc_ValueError, "Only grayscale PNG bit depth 1/2/4/8 is supported.");
                    return NULL;
                }
            } else if (bit_depth != 8) {
                Py_DECREF(idat);
                PyBuffer_Release(&in_buf);
                PyErr_SetString(PyExc_ValueError, "Only 8-bit RGB/RGBA PNG is supported.");
                return NULL;
            }
        } else if (memcmp(ctype, "IDAT", 4) == 0) {
            Py_ssize_t old_len = PyBytes_GET_SIZE(idat);
            PyObject *new_idat = PyBytes_FromStringAndSize(NULL, old_len + chunk_len);
            if (new_idat == NULL) {
                Py_DECREF(idat);
                PyBuffer_Release(&in_buf);
                return NULL;
            }
            memcpy(PyBytes_AS_STRING(new_idat), PyBytes_AS_STRING(idat), (size_t)old_len);
            memcpy(PyBytes_AS_STRING(new_idat) + old_len, payload, chunk_len);
            Py_DECREF(idat);
            idat = new_idat;
        } else if (memcmp(ctype, "IEND", 4) == 0) {
            break;
        }
    }

    idat_len = PyBytes_GET_SIZE(idat);
    if (width <= 0 || height <= 0) {
        Py_DECREF(idat);
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid PNG: missing IHDR.");
        return NULL;
    }
    if (idat_len <= 0) {
        Py_DECREF(idat);
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid PNG: missing IDAT.");
        return NULL;
    }

    channels = color_type == 0 ? 1 : (color_type == 2 ? 3 : 4);
    grayscale_packed = (color_type == 0 && bit_depth < 8) ? 1 : 0;
    if (grayscale_packed) {
        stride = ((Py_ssize_t)width * bit_depth + 7) / 8;
    } else {
        stride = (Py_ssize_t)width * channels;
    }
    expected = (stride + 1) * height;
    idat_ptr = (uint8_t *)PyBytes_AS_STRING(idat);

    zlib_mod = PyImport_ImportModule("zlib");
    if (zlib_mod == NULL) {
        Py_DECREF(idat);
        PyBuffer_Release(&in_buf);
        return NULL;
    }
    raw_obj = PyObject_CallMethod(zlib_mod, "decompress", "y#", idat_ptr, idat_len);
    Py_DECREF(zlib_mod);
    Py_DECREF(idat);
    if (raw_obj == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }
    if (!PyBytes_Check(raw_obj)) {
        Py_DECREF(raw_obj);
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid PNG data length.");
        return NULL;
    }
    raw = (const uint8_t *)PyBytes_AS_STRING(raw_obj);
    raw_len = PyBytes_GET_SIZE(raw_obj);
    if (raw_len != expected) {
        Py_DECREF(raw_obj);
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid PNG data length.");
        return NULL;
    }

    if (color_type == 0) {
        out = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)width * height);
    } else {
        out = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)width * height * channels);
    }
    if (out == NULL) {
        Py_DECREF(raw_obj);
        PyBuffer_Release(&in_buf);
        return NULL;
    }
    out_ptr = (uint8_t *)PyBytes_AS_STRING(out);
    prev = (uint8_t *)PyMem_Calloc((size_t)stride, 1);
    row = (uint8_t *)PyMem_Malloc((size_t)stride);
    if (prev == NULL || row == NULL) {
        Py_XDECREF(out);
        Py_DECREF(raw_obj);
        PyBuffer_Release(&in_buf);
        if (prev != NULL) {
            PyMem_Free(prev);
        }
        if (row != NULL) {
            PyMem_Free(row);
        }
        PyErr_NoMemory();
        return NULL;
    }

    for (y = 0; y < height; y++) {
        Py_ssize_t src = (stride + 1) * y;
        int filter_type = raw[src];
        Py_ssize_t i;
        src += 1;
        memcpy(row, raw + src, (size_t)stride);
        if (filter_type == 1) {
            for (i = 0; i < stride; i++) {
                uint8_t left = i >= channels ? row[i - channels] : 0;
                row[i] = (uint8_t)((row[i] + left) & 0xFF);
            }
        } else if (filter_type == 2) {
            for (i = 0; i < stride; i++) {
                row[i] = (uint8_t)((row[i] + prev[i]) & 0xFF);
            }
        } else if (filter_type == 3) {
            for (i = 0; i < stride; i++) {
                uint8_t left = i >= channels ? row[i - channels] : 0;
                uint8_t up = prev[i];
                row[i] = (uint8_t)((row[i] + ((left + up) / 2)) & 0xFF);
            }
        } else if (filter_type == 4) {
            for (i = 0; i < stride; i++) {
                int left = i >= channels ? row[i - channels] : 0;
                int up = prev[i];
                int up_left = i >= channels ? prev[i - channels] : 0;
                row[i] = (uint8_t)((row[i] + paeth_predictor(left, up, up_left)) & 0xFF);
            }
        } else if (filter_type != 0) {
            PyMem_Free(prev);
            PyMem_Free(row);
            Py_DECREF(raw_obj);
            Py_DECREF(out);
            PyBuffer_Release(&in_buf);
            PyErr_Format(PyExc_ValueError, "Unsupported PNG filter type: %d", filter_type);
            return NULL;
        }
        if (grayscale_packed) {
            expand_packed_grayscale_row(row, width, bit_depth, out_ptr + (Py_ssize_t)y * width);
        } else {
            memcpy(out_ptr + (Py_ssize_t)y * stride, row, (size_t)stride);
        }
        memcpy(prev, row, (size_t)stride);
    }

    PyMem_Free(prev);
    PyMem_Free(row);
    Py_DECREF(raw_obj);
    PyBuffer_Release(&in_buf);
    if (color_type == 0) {
        return build_decode_result("L", width, height, out);
    }
    if (color_type == 2) {
        return build_decode_result("RGB", width, height, out);
    }
    return build_decode_result("RGBA", width, height, out);
}

static PyObject *
cimage_encode_png_8bit(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    const char *mode;
    int width;
    int height;
    int channels;
    int color_type;
    Py_ssize_t stride;
    Py_ssize_t raw_len;
    PyObject *raw_obj = NULL;
    uint8_t *raw_ptr;
    int y;
    PyObject *zlib_mod = NULL;
    PyObject *compressed = NULL;
    uint8_t *comp_ptr;
    Py_ssize_t comp_len;
    Py_ssize_t out_len;
    PyObject *out = NULL;
    uint8_t *out_ptr;
    uint8_t ihdr_payload[13];
    uint8_t crc_buf[4 + 13];
    uint32_t crc;
    Py_ssize_t pos = 0;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*sii", &in_buf, &mode, &width, &height)) {
        return NULL;
    }
    channels = channels_from_mode(mode);
    if (channels < 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Unsupported mode.");
        return NULL;
    }
    if (width <= 0 || height <= 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid image size.");
        return NULL;
    }
    if (in_buf.len != (Py_ssize_t)width * height * channels) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Raw data length mismatch.");
        return NULL;
    }

    if (channels == 1) {
        color_type = 0;
    } else if (channels == 3) {
        color_type = 2;
    } else if (channels == 4) {
        color_type = 6;
    } else {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Unsupported mode.");
        return NULL;
    }

    stride = (Py_ssize_t)width * channels;
    raw_len = (stride + 1) * height;
    raw_obj = PyBytes_FromStringAndSize(NULL, raw_len);
    if (raw_obj == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }
    raw_ptr = (uint8_t *)PyBytes_AS_STRING(raw_obj);
    for (y = 0; y < height; y++) {
        Py_ssize_t dst = (stride + 1) * y;
        Py_ssize_t src = stride * y;
        raw_ptr[dst] = 0;
        memcpy(raw_ptr + dst + 1, (const uint8_t *)in_buf.buf + src, (size_t)stride);
    }

    zlib_mod = PyImport_ImportModule("zlib");
    if (zlib_mod == NULL) {
        Py_DECREF(raw_obj);
        PyBuffer_Release(&in_buf);
        return NULL;
    }
    compressed = PyObject_CallMethod(zlib_mod, "compress", "y#i", raw_ptr, raw_len, 6);
    Py_DECREF(zlib_mod);
    Py_DECREF(raw_obj);
    if (compressed == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }
    if (!PyBytes_Check(compressed)) {
        Py_DECREF(compressed);
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Failed to encode PNG.");
        return NULL;
    }
    comp_ptr = (uint8_t *)PyBytes_AS_STRING(compressed);
    comp_len = PyBytes_GET_SIZE(compressed);

    out_len = 8 + (12 + 13) + (12 + comp_len) + 12;
    out = PyBytes_FromStringAndSize(NULL, out_len);
    if (out == NULL) {
        Py_DECREF(compressed);
        PyBuffer_Release(&in_buf);
        return NULL;
    }
    out_ptr = (uint8_t *)PyBytes_AS_STRING(out);
    memcpy(out_ptr + pos, "\x89PNG\r\n\x1a\n", 8);
    pos += 8;

    write_u32_be(out_ptr + pos, 13);
    pos += 4;
    memcpy(out_ptr + pos, "IHDR", 4);
    pos += 4;
    write_u32_be(ihdr_payload, (uint32_t)width);
    write_u32_be(ihdr_payload + 4, (uint32_t)height);
    ihdr_payload[8] = 8;
    ihdr_payload[9] = (uint8_t)color_type;
    ihdr_payload[10] = 0;
    ihdr_payload[11] = 0;
    ihdr_payload[12] = 0;
    memcpy(out_ptr + pos, ihdr_payload, 13);
    pos += 13;
    memcpy(crc_buf, "IHDR", 4);
    memcpy(crc_buf + 4, ihdr_payload, 13);
    crc = png_crc32(crc_buf, 17);
    write_u32_be(out_ptr + pos, crc);
    pos += 4;

    write_u32_be(out_ptr + pos, (uint32_t)comp_len);
    pos += 4;
    memcpy(out_ptr + pos, "IDAT", 4);
    pos += 4;
    memcpy(out_ptr + pos, comp_ptr, (size_t)comp_len);
    pos += comp_len;
    crc = png_crc32((const uint8_t *)"IDAT", 4);
    crc = png_crc32(comp_ptr, comp_len) ^ (crc ^ 0xFFFFFFFFU); /* combine with simple xor chain */
    /* fallback exact crc by contiguous buffer */
    {
        uint8_t *tmp = (uint8_t *)PyMem_Malloc((size_t)(4 + comp_len));
        if (tmp == NULL) {
            Py_DECREF(compressed);
            Py_DECREF(out);
            PyBuffer_Release(&in_buf);
            PyErr_NoMemory();
            return NULL;
        }
        memcpy(tmp, "IDAT", 4);
        memcpy(tmp + 4, comp_ptr, (size_t)comp_len);
        crc = png_crc32(tmp, 4 + comp_len);
        PyMem_Free(tmp);
    }
    write_u32_be(out_ptr + pos, crc);
    pos += 4;

    write_u32_be(out_ptr + pos, 0);
    pos += 4;
    memcpy(out_ptr + pos, "IEND", 4);
    pos += 4;
    crc = png_crc32((const uint8_t *)"IEND", 4);
    write_u32_be(out_ptr + pos, crc);
    pos += 4;

    Py_DECREF(compressed);
    PyBuffer_Release(&in_buf);
    return out;
}

static PyObject *
cimage_threshold_to_bits(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    const char *mode;
    int width;
    int height;
    int threshold;
    int channels;
    Py_ssize_t pixels;
    const uint8_t *src;
    PyObject *out;
    uint8_t *dst;
    Py_ssize_t i;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*siii", &in_buf, &mode, &width, &height, &threshold)) {
        return NULL;
    }

    channels = channels_from_mode(mode);
    if (channels < 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Unsupported mode.");
        return NULL;
    }
    if (width <= 0 || height <= 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid image size.");
        return NULL;
    }
    pixels = (Py_ssize_t)width * (Py_ssize_t)height;
    if (in_buf.len != pixels * channels) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Raw data length mismatch.");
        return NULL;
    }
    if (threshold < 0) {
        threshold = 0;
    }
    if (threshold > 255) {
        threshold = 255;
    }

    out = PyBytes_FromStringAndSize(NULL, pixels);
    if (out == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }
    src = (const uint8_t *)in_buf.buf;
    dst = (uint8_t *)PyBytes_AS_STRING(out);

    if (channels == 1) {
        for (i = 0; i < pixels; i++) {
            dst[i] = src[i] < threshold ? 1 : 0;
        }
    } else if (channels == 3) {
        for (i = 0; i < pixels; i++) {
            const uint8_t *sp = src + i * 3;
            int gray = (299 * sp[0] + 587 * sp[1] + 114 * sp[2]) / 1000;
            dst[i] = gray < threshold ? 1 : 0;
        }
    } else {
        for (i = 0; i < pixels; i++) {
            const uint8_t *sp = src + i * 4;
            int gray;
            if (sp[3] <= 127) {
                dst[i] = 0;
                continue;
            }
            gray = (299 * sp[0] + 587 * sp[1] + 114 * sp[2]) / 1000;
            dst[i] = gray < threshold ? 1 : 0;
        }
    }

    PyBuffer_Release(&in_buf);
    return out;
}

static PyObject *
cimage_sixel_encode_mono(PyObject *self, PyObject *args)
{
    Py_buffer bits_buf;
    int width;
    int height;
    int y;
    Py_ssize_t expected;
    const uint8_t *bits;
    PyObject *parts;
    PyObject *sep;
    PyObject *result;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*ii", &bits_buf, &width, &height)) {
        return NULL;
    }
    if (width <= 0 || height <= 0) {
        PyBuffer_Release(&bits_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid image size.");
        return NULL;
    }
    expected = (Py_ssize_t)width * (Py_ssize_t)height;
    if (bits_buf.len != expected) {
        PyBuffer_Release(&bits_buf);
        PyErr_SetString(PyExc_ValueError, "Bits length mismatch.");
        return NULL;
    }

    bits = (const uint8_t *)bits_buf.buf;
    parts = PyList_New(0);
    if (parts == NULL) {
        PyBuffer_Release(&bits_buf);
        return NULL;
    }

    for (y = 0; y < height; y += 6) {
        int max_i = (height - y) < 6 ? (height - y) : 6;
        PyObject *white_prefix = PyUnicode_FromString("#0");
        PyObject *white_line = NULL;
        PyObject *dollar = PyUnicode_FromString("$");
        PyObject *black_prefix = PyUnicode_FromString("#1");
        PyObject *black_line = NULL;
        PyObject *dash = PyUnicode_FromString("-");
        char *white_buf = (char *)PyMem_Malloc((size_t)width + 1U);
        char *black_buf = (char *)PyMem_Malloc((size_t)width + 1U);
        int x;
        int white_end;
        int black_end;

        if (
            white_prefix == NULL || dollar == NULL || black_prefix == NULL || dash == NULL
            || white_buf == NULL || black_buf == NULL
        ) {
            Py_XDECREF(white_prefix);
            Py_XDECREF(dollar);
            Py_XDECREF(black_prefix);
            Py_XDECREF(dash);
            if (white_buf != NULL) {
                PyMem_Free(white_buf);
            }
            if (black_buf != NULL) {
                PyMem_Free(black_buf);
            }
            Py_DECREF(parts);
            PyBuffer_Release(&bits_buf);
            PyErr_NoMemory();
            return NULL;
        }

        for (x = 0; x < width; x++) {
            int i;
            int white_val = 0;
            int black_val = 0;
            for (i = 0; i < max_i; i++) {
                int bit = bits[(Py_ssize_t)(y + i) * width + x] ? 1 : 0;
                if (bit == 0) {
                    white_val |= (1 << i);
                } else {
                    black_val |= (1 << i);
                }
            }
            white_buf[x] = (char)(white_val + 63);
            black_buf[x] = (char)(black_val + 63);
        }
        white_end = width;
        black_end = width;
        while (white_end > 0 && white_buf[white_end - 1] == '?') {
            white_end--;
        }
        while (black_end > 0 && black_buf[black_end - 1] == '?') {
            black_end--;
        }
        white_line = PyUnicode_FromStringAndSize(white_buf, white_end);
        black_line = PyUnicode_FromStringAndSize(black_buf, black_end);
        PyMem_Free(white_buf);
        PyMem_Free(black_buf);
        if (white_line == NULL || black_line == NULL) {
            Py_XDECREF(white_prefix);
            Py_XDECREF(white_line);
            Py_XDECREF(dollar);
            Py_XDECREF(black_prefix);
            Py_XDECREF(black_line);
            Py_XDECREF(dash);
            Py_DECREF(parts);
            PyBuffer_Release(&bits_buf);
            return NULL;
        }

        if (
            PyList_Append(parts, white_prefix) < 0
            || (white_end > 0 && PyList_Append(parts, white_line) < 0)
            || PyList_Append(parts, dollar) < 0
            || PyList_Append(parts, black_prefix) < 0
            || (black_end > 0 && PyList_Append(parts, black_line) < 0)
            || PyList_Append(parts, dash) < 0
        ) {
            Py_DECREF(white_prefix);
            Py_DECREF(white_line);
            Py_DECREF(dollar);
            Py_DECREF(black_prefix);
            Py_DECREF(black_line);
            Py_DECREF(dash);
            Py_DECREF(parts);
            PyBuffer_Release(&bits_buf);
            return NULL;
        }

        Py_DECREF(white_prefix);
        Py_DECREF(white_line);
        Py_DECREF(dollar);
        Py_DECREF(black_prefix);
        Py_DECREF(black_line);
        Py_DECREF(dash);
    }

    sep = PyUnicode_FromString("");
    if (sep == NULL) {
        Py_DECREF(parts);
        PyBuffer_Release(&bits_buf);
        return NULL;
    }
    result = PyUnicode_Join(sep, parts);
    Py_DECREF(sep);
    Py_DECREF(parts);
    PyBuffer_Release(&bits_buf);
    return result;
}

static PyMethodDef cimage_methods[] = {
    {"convert", cimage_convert, METH_VARARGS, "Convert image mode."},
    {"getbbox_nonwhite", cimage_getbbox_nonwhite, METH_VARARGS, "Get non-white bbox."},
    {"resize_nearest", cimage_resize_nearest, METH_VARARGS, "Nearest resize."},
    {"decode_png_8bit", cimage_decode_png_8bit, METH_VARARGS, "Decode PNG bytes to raw image."},
    {"encode_png_8bit", cimage_encode_png_8bit, METH_VARARGS, "Encode raw image to PNG bytes."},
    {"threshold_to_bits", cimage_threshold_to_bits, METH_VARARGS, "Threshold image to 0/1 bits."},
    {"sixel_encode_mono", cimage_sixel_encode_mono, METH_VARARGS, "Encode mono bits to sixel body."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef cimage_module = {
    PyModuleDef_HEAD_INIT,
    "_cimage",
    "Optional C acceleration for SimpleImage.",
    -1,
    cimage_methods,
};

PyMODINIT_FUNC
PyInit__cimage(void)
{
    return PyModule_Create(&cimage_module);
}
