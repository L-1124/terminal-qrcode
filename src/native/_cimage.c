#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>

#include <png.h>
#include <turbojpeg.h>
#include <webp/decode.h>
#include <webp/types.h>

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

typedef struct {
    const uint8_t *data;
    size_t size;
    size_t offset;
} PngReadState;

static void
png_read_cb(png_structp png_ptr, png_bytep out, png_size_t bytes)
{
    PngReadState *state = (PngReadState *)png_get_io_ptr(png_ptr);
    if (state == NULL || state->offset + bytes > state->size) {
        png_error(png_ptr, "PNG read out of range");
        return;
    }
    memcpy(out, state->data + state->offset, bytes);
    state->offset += bytes;
}

typedef struct {
    uint8_t *data;
    size_t size;
    size_t cap;
} PngWriteState;

static int
png_write_reserve(PngWriteState *state, size_t need)
{
    uint8_t *new_data;
    size_t new_cap;

    if (state->size + need <= state->cap) {
        return 0;
    }

    new_cap = state->cap == 0 ? 8192 : state->cap;
    while (new_cap < state->size + need) {
        if (new_cap > (SIZE_MAX / 2)) {
            return -1;
        }
        new_cap *= 2;
    }

    new_data = (uint8_t *)PyMem_Realloc(state->data, new_cap);
    if (new_data == NULL) {
        return -1;
    }

    state->data = new_data;
    state->cap = new_cap;
    return 0;
}

static void
png_write_cb(png_structp png_ptr, png_bytep data, png_size_t length)
{
    PngWriteState *state = (PngWriteState *)png_get_io_ptr(png_ptr);
    if (state == NULL || png_write_reserve(state, (size_t)length) != 0) {
        png_error(png_ptr, "PNG write OOM");
        return;
    }
    memcpy(state->data + state->size, data, length);
    state->size += length;
}

static void
png_flush_cb(png_structp png_ptr)
{
    (void)png_ptr;
}

static int
decode_png_to_mode_pixels(
    const uint8_t *png_data,
    size_t png_size,
    const char **out_mode,
    int *out_width,
    int *out_height,
    PyObject **out_pixels
)
{
    png_structp png_ptr = NULL;
    png_infop info_ptr = NULL;
    PngReadState read_state;
    png_bytep *rows = NULL;
    int width;
    int height;
    int bit_depth;
    int color_type;
    int has_alpha;
    const char *mode;
    int channels;
    png_size_t rowbytes;
    PyObject *pixels = NULL;
    uint8_t *dst;
    int y;

    *out_mode = NULL;
    *out_width = 0;
    *out_height = 0;
    *out_pixels = NULL;

    if (png_size < 8 || png_sig_cmp((png_bytep)png_data, 0, 8) != 0) {
        PyErr_SetString(PyExc_ValueError, "Only PNG images are supported.");
        return -1;
    }

    png_ptr = png_create_read_struct(PNG_LIBPNG_VER_STRING, NULL, NULL, NULL);
    if (png_ptr == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to create libpng read struct.");
        return -1;
    }

    info_ptr = png_create_info_struct(png_ptr);
    if (info_ptr == NULL) {
        png_destroy_read_struct(&png_ptr, NULL, NULL);
        PyErr_SetString(PyExc_RuntimeError, "Failed to create libpng info struct.");
        return -1;
    }

    if (setjmp(png_jmpbuf(png_ptr))) {
        if (rows != NULL) {
            PyMem_Free(rows);
        }
        Py_XDECREF(pixels);
        png_destroy_read_struct(&png_ptr, &info_ptr, NULL);
        PyErr_SetString(PyExc_ValueError, "libpng decode failed.");
        return -1;
    }

    read_state.data = png_data;
    read_state.size = png_size;
    read_state.offset = 0;

    png_set_read_fn(png_ptr, &read_state, png_read_cb);
    png_read_info(png_ptr, info_ptr);

    width = (int)png_get_image_width(png_ptr, info_ptr);
    height = (int)png_get_image_height(png_ptr, info_ptr);
    bit_depth = png_get_bit_depth(png_ptr, info_ptr);
    color_type = png_get_color_type(png_ptr, info_ptr);
    has_alpha =
        (color_type == PNG_COLOR_TYPE_GRAY_ALPHA)
        || (color_type == PNG_COLOR_TYPE_RGBA)
        || (png_get_valid(png_ptr, info_ptr, PNG_INFO_tRNS) != 0);

    if (width <= 0 || height <= 0) {
        png_error(png_ptr, "Invalid PNG size");
    }

    if (bit_depth == 16) {
        png_set_strip_16(png_ptr);
    }

    if (color_type == PNG_COLOR_TYPE_PALETTE) {
        png_set_palette_to_rgb(png_ptr);
    }

    if (color_type == PNG_COLOR_TYPE_GRAY && bit_depth < 8) {
        png_set_expand_gray_1_2_4_to_8(png_ptr);
    }

    if (png_get_valid(png_ptr, info_ptr, PNG_INFO_tRNS) != 0) {
        png_set_tRNS_to_alpha(png_ptr);
        has_alpha = 1;
    }

    if (has_alpha) {
        if (color_type == PNG_COLOR_TYPE_GRAY || color_type == PNG_COLOR_TYPE_GRAY_ALPHA) {
            png_set_gray_to_rgb(png_ptr);
        }
        mode = "RGBA";
        channels = 4;
        if (!(color_type == PNG_COLOR_TYPE_GRAY_ALPHA || color_type == PNG_COLOR_TYPE_RGBA)) {
            png_set_add_alpha(png_ptr, 0xFF, PNG_FILLER_AFTER);
        }
    } else if (color_type == PNG_COLOR_TYPE_GRAY || color_type == PNG_COLOR_TYPE_GRAY_ALPHA) {
        mode = "L";
        channels = 1;
        if (color_type == PNG_COLOR_TYPE_GRAY_ALPHA) {
            png_set_strip_alpha(png_ptr);
        }
    } else {
        mode = "RGB";
        channels = 3;
        if (color_type == PNG_COLOR_TYPE_RGBA || color_type == PNG_COLOR_TYPE_GRAY_ALPHA) {
            png_set_strip_alpha(png_ptr);
        }
    }

    png_read_update_info(png_ptr, info_ptr);
    rowbytes = png_get_rowbytes(png_ptr, info_ptr);
    if ((size_t)rowbytes != (size_t)width * (size_t)channels) {
        png_error(png_ptr, "Unexpected PNG row bytes");
    }

    pixels = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)width * height * channels);
    if (pixels == NULL) {
        png_error(png_ptr, "OOM");
    }

    dst = (uint8_t *)PyBytes_AS_STRING(pixels);
    rows = (png_bytep *)PyMem_Malloc(sizeof(png_bytep) * (size_t)height);
    if (rows == NULL) {
        png_error(png_ptr, "OOM");
    }

    for (y = 0; y < height; y++) {
        rows[y] = dst + (size_t)y * (size_t)width * (size_t)channels;
    }

    png_read_image(png_ptr, rows);
    png_read_end(png_ptr, NULL);

    PyMem_Free(rows);
    png_destroy_read_struct(&png_ptr, &info_ptr, NULL);

    *out_mode = mode;
    *out_width = width;
    *out_height = height;
    *out_pixels = pixels;
    return 0;
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

    if (pixels > 0 && dst_channels > (PY_SSIZE_T_MAX / pixels)) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_OverflowError, "Output image size too large.");
        return NULL;
    }

    out = PyBytes_FromStringAndSize(NULL, pixels * dst_channels);
    if (out == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }

    src = (const uint8_t *)in_buf.buf;
    dst = (uint8_t *)PyBytes_AS_STRING(out);

    Py_BEGIN_ALLOW_THREADS
    if (strcmp(src_mode, "L") == 0) {
        if (dst_channels == 1) {
            for (i = 0; i < pixels; i++) {
                dst[i] = src[i];
            }
        } else if (dst_channels == 3) {
            for (i = 0; i < pixels; i++) {
                dst[i*3] = dst[i*3+1] = dst[i*3+2] = src[i];
            }
        } else if (dst_channels == 4) {
            for (i = 0; i < pixels; i++) {
                dst[i*4] = dst[i*4+1] = dst[i*4+2] = src[i];
                dst[i*4+3] = 255;
            }
        }
    } else if (strcmp(src_mode, "RGB") == 0 || strcmp(src_mode, "RGBA") == 0) {
        if (dst_channels == 1) {
            for (i = 0; i < pixels; i++) {
                const uint8_t *sp = src + i * src_channels;
                dst[i] = (uint8_t)((299 * sp[0] + 587 * sp[1] + 114 * sp[2]) / 1000);
            }
        } else if (dst_channels == 3) {
            if (src_channels == 3) {
                memcpy(dst, src, (size_t)pixels * 3);
            } else {
                for (i = 0; i < pixels; i++) {
                    const uint8_t *sp = src + i * 4;
                    uint8_t *dp = dst + i * 3;
                    dp[0] = sp[0]; dp[1] = sp[1]; dp[2] = sp[2];
                }
            }
        } else if (dst_channels == 4) {
            if (src_channels == 4) {
                memcpy(dst, src, (size_t)pixels * 4);
            } else {
                for (i = 0; i < pixels; i++) {
                    const uint8_t *sp = src + i * 3;
                    uint8_t *dp = dst + i * 4;
                    dp[0] = sp[0]; dp[1] = sp[1]; dp[2] = sp[2]; dp[3] = 255;
                }
            }
        }
    }
    Py_END_ALLOW_THREADS

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
    int *map_x, *map_y;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*siiii", &in_buf, &mode, &src_w, &src_h, &dst_w, &dst_h)) {
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

    if (dst_h > 0 && dst_w > (PY_SSIZE_T_MAX / dst_h / channels)) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_OverflowError, "Resized image dimensions too large.");
        return NULL;
    }

    out = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)dst_w * dst_h * channels);
    if (out == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }

    src = (const uint8_t *)in_buf.buf;
    dst = (uint8_t *)PyBytes_AS_STRING(out);

    /* Precompute mapping tables to avoid division in inner loop */
    map_x = (int *)PyMem_Malloc(sizeof(int) * (size_t)dst_w);
    map_y = (int *)PyMem_Malloc(sizeof(int) * (size_t)dst_h);
    if (map_x == NULL || map_y == NULL) {
        Py_XDECREF(out);
        if (map_x) PyMem_Free(map_x);
        if (map_y) PyMem_Free(map_y);
        PyBuffer_Release(&in_buf);
        return PyErr_NoMemory();
    }

    for (x = 0; x < dst_w; x++) {
        map_x[x] = (x * src_w) / dst_w;
        if (map_x[x] >= src_w) map_x[x] = src_w - 1;
    }
    for (y = 0; y < dst_h; y++) {
        map_y[y] = (y * src_h) / dst_h;
        if (map_y[y] >= src_h) map_y[y] = src_h - 1;
    }

    Py_BEGIN_ALLOW_THREADS
    for (y = 0; y < dst_h; y++) {
        int sy = map_y[y];
        int src_row_base = sy * src_w;
        int dst_row_base = y * dst_w;
        for (x = 0; x < dst_w; x++) {
            int sx = map_x[x];
            int src_idx = (src_row_base + sx) * channels;
            int dst_idx = (dst_row_base + x) * channels;
            memcpy(dst + dst_idx, src + src_idx, (size_t)channels);
        }
    }
    Py_END_ALLOW_THREADS

    PyMem_Free(map_x);
    PyMem_Free(map_y);
    PyBuffer_Release(&in_buf);
    return out;
}

static PyObject *
cimage_decode_png_8bit(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    const char *mode;
    int width;
    int height;
    PyObject *pixels;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*", &in_buf)) {
        return NULL;
    }

    if (decode_png_to_mode_pixels((const uint8_t *)in_buf.buf, (size_t)in_buf.len, &mode, &width, &height, &pixels)
        != 0) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }

    PyBuffer_Release(&in_buf);
    return build_decode_result(mode, width, height, pixels);
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
    png_structp png_ptr = NULL;
    png_infop info_ptr = NULL;
    PngWriteState state;
    png_bytep *rows = NULL;
    int y;
    PyObject *out;

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
        color_type = PNG_COLOR_TYPE_GRAY;
    } else if (channels == 3) {
        color_type = PNG_COLOR_TYPE_RGB;
    } else {
        color_type = PNG_COLOR_TYPE_RGBA;
    }

    state.data = NULL;
    state.size = 0;
    state.cap = 0;

    png_ptr = png_create_write_struct(PNG_LIBPNG_VER_STRING, NULL, NULL, NULL);
    if (png_ptr == NULL) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_RuntimeError, "Failed to create libpng write struct.");
        return NULL;
    }

    info_ptr = png_create_info_struct(png_ptr);
    if (info_ptr == NULL) {
        png_destroy_write_struct(&png_ptr, NULL);
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_RuntimeError, "Failed to create libpng info struct.");
        return NULL;
    }

    if (setjmp(png_jmpbuf(png_ptr))) {
        if (rows != NULL) {
            PyMem_Free(rows);
        }
        if (state.data != NULL) {
            PyMem_Free(state.data);
        }
        png_destroy_write_struct(&png_ptr, &info_ptr);
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "libpng encode failed.");
        return NULL;
    }

    png_set_write_fn(png_ptr, &state, png_write_cb, png_flush_cb);
    png_set_IHDR(
        png_ptr,
        info_ptr,
        (png_uint_32)width,
        (png_uint_32)height,
        8,
        color_type,
        PNG_INTERLACE_NONE,
        PNG_COMPRESSION_TYPE_DEFAULT,
        PNG_FILTER_TYPE_DEFAULT
    );

    png_write_info(png_ptr, info_ptr);

    rows = (png_bytep *)PyMem_Malloc(sizeof(png_bytep) * (size_t)height);
    if (rows == NULL) {
        png_error(png_ptr, "OOM");
    }

    for (y = 0; y < height; y++) {
        rows[y] = (png_bytep)((const uint8_t *)in_buf.buf + (size_t)y * (size_t)width * (size_t)channels);
    }

    png_write_image(png_ptr, rows);
    png_write_end(png_ptr, info_ptr);

    PyMem_Free(rows);
    png_destroy_write_struct(&png_ptr, &info_ptr);
    PyBuffer_Release(&in_buf);

    out = PyBytes_FromStringAndSize((const char *)state.data, (Py_ssize_t)state.size);
    if (state.data != NULL) {
        PyMem_Free(state.data);
    }
    return out;
}

static PyObject *
cimage_decode_jpeg_turbo(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    tjhandle handle = NULL;
    int width = 0;
    int height = 0;
    int jpeg_subsamp = 0;
    int jpeg_colorspace = 0;
    PyObject *pixels = NULL;
    unsigned char *dst;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*", &in_buf)) {
        return NULL;
    }

    handle = tjInitDecompress();
    if (handle == NULL) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_RuntimeError, "tjInitDecompress failed.");
        return NULL;
    }

    if (tjDecompressHeader3(
            handle,
            (const unsigned char *)in_buf.buf,
            (unsigned long)in_buf.len,
            &width,
            &height,
            &jpeg_subsamp,
            &jpeg_colorspace
        ) != 0) {
        tjDestroy(handle);
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, tjGetErrorStr());
        return NULL;
    }

    (void)jpeg_subsamp;
    (void)jpeg_colorspace;

    if (width <= 0 || height <= 0) {
        tjDestroy(handle);
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid JPEG size.");
        return NULL;
    }

    pixels = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)width * height * 3);
    if (pixels == NULL) {
        tjDestroy(handle);
        PyBuffer_Release(&in_buf);
        return NULL;
    }

    dst = (unsigned char *)PyBytes_AS_STRING(pixels);
    Py_BEGIN_ALLOW_THREADS
    if (tjDecompress2(
            handle,
            (const unsigned char *)in_buf.buf,
            (unsigned long)in_buf.len,
            dst,
            width,
            0,
            height,
            TJPF_RGB,
            TJFLAG_FASTDCT
        ) != 0) {
        Py_BLOCK_THREADS
        tjDestroy(handle);
        Py_DECREF(pixels);
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, tjGetErrorStr());
        return NULL;
    }
    Py_END_ALLOW_THREADS

    tjDestroy(handle);
    PyBuffer_Release(&in_buf);
    return Py_BuildValue("(iiN)", width, height, pixels);
}

static PyObject *
cimage_decode_webp_lib(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    int width = 0;
    int height = 0;
    uint8_t *decoded = NULL;
    PyObject *pixels = NULL;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*", &in_buf)) {
        return NULL;
    }

    Py_BEGIN_ALLOW_THREADS
    decoded = WebPDecodeRGBA((const uint8_t *)in_buf.buf, (size_t)in_buf.len, &width, &height);
    Py_END_ALLOW_THREADS
    if (decoded == NULL || width <= 0 || height <= 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "WebP decode failed.");
        return NULL;
    }

    pixels = PyBytes_FromStringAndSize((const char *)decoded, (Py_ssize_t)width * height * 4);
    WebPFree(decoded);
    PyBuffer_Release(&in_buf);

    if (pixels == NULL) {
        return NULL;
    }

    return Py_BuildValue("(iiN)", width, height, pixels);
}

static PyObject *
threshold_to_bits_raw(
    const uint8_t *src,
    const char *mode,
    int width,
    int height,
    int threshold
)
{
    int channels = channels_from_mode(mode);
    Py_ssize_t pixels;
    PyObject *out;
    uint8_t *dst;
    Py_ssize_t i;

    if (channels < 0) {
        PyErr_SetString(PyExc_ValueError, "Unsupported mode.");
        return NULL;
    }
    if (width <= 0 || height <= 0) {
        PyErr_SetString(PyExc_ValueError, "Invalid image size.");
        return NULL;
    }

    if (width > (PY_SSIZE_T_MAX / height)) {
        PyErr_SetString(PyExc_OverflowError, "Image dimensions too large.");
        return NULL;
    }
    pixels = (Py_ssize_t)width * (Py_ssize_t)height;
    if (threshold < 0) {
        threshold = 0;
    }
    if (threshold > 255) {
        threshold = 255;
    }

    out = PyBytes_FromStringAndSize(NULL, pixels);
    if (out == NULL) {
        return NULL;
    }
    dst = (uint8_t *)PyBytes_AS_STRING(out);

    Py_BEGIN_ALLOW_THREADS
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
            /* Branchless alpha check: if sp[3] <= 127, mask is 0, else mask is -1 (all 1s) */
            int32_t is_transparent = ((int32_t)sp[3] - 128) >> 31;
            int gray = (299 * sp[0] + 587 * sp[1] + 114 * sp[2]) / 1000;
            int bit = (gray < threshold);
            dst[i] = (uint8_t)(bit & ~is_transparent);
        }
    }
    Py_END_ALLOW_THREADS

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
    if (width > (PY_SSIZE_T_MAX / height)) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_OverflowError, "Image dimensions too large.");
        return NULL;
    }
    pixels = (Py_ssize_t)width * (Py_ssize_t)height;
    if (in_buf.len != pixels * channels) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Raw data length mismatch.");
        return NULL;
    }

    src = (const uint8_t *)in_buf.buf;
    out = threshold_to_bits_raw(src, mode, width, height, threshold);
    PyBuffer_Release(&in_buf);
    return out;
}

static const char *const SIXEL_RLE_LOOKUP[256] = {
    "!0", "!1", "!2", "!3", "!4", "!5", "!6", "!7", "!8", "!9",
    "!10", "!11", "!12", "!13", "!14", "!15", "!16", "!17", "!18", "!19",
    "!20", "!21", "!22", "!23", "!24", "!25", "!26", "!27", "!28", "!29",
    "!30", "!31", "!32", "!33", "!34", "!35", "!36", "!37", "!38", "!39",
    "!40", "!41", "!42", "!43", "!44", "!45", "!46", "!47", "!48", "!49",
    "!50", "!51", "!52", "!53", "!54", "!55", "!56", "!57", "!58", "!59",
    "!60", "!61", "!62", "!63", "!64", "!65", "!66", "!67", "!68", "!69",
    "!70", "!71", "!72", "!73", "!74", "!75", "!76", "!77", "!78", "!79",
    "!80", "!81", "!82", "!83", "!84", "!85", "!86", "!87", "!88", "!89",
    "!90", "!91", "!92", "!93", "!94", "!95", "!96", "!97", "!98", "!99",
    "!100", "!101", "!102", "!103", "!104", "!105", "!106", "!107", "!108", "!109",
    "!110", "!111", "!112", "!113", "!114", "!115", "!116", "!117", "!118", "!119",
    "!120", "!121", "!122", "!123", "!124", "!125", "!126", "!127", "!128", "!129",
    "!130", "!131", "!132", "!133", "!134", "!135", "!136", "!137", "!138", "!139",
    "!140", "!141", "!142", "!143", "!144", "!145", "!146", "!147", "!148", "!149",
    "!150", "!151", "!152", "!153", "!154", "!155", "!156", "!157", "!158", "!159",
    "!160", "!161", "!162", "!163", "!164", "!165", "!166", "!167", "!168", "!169",
    "!170", "!171", "!172", "!173", "!174", "!175", "!176", "!177", "!178", "!179",
    "!180", "!181", "!182", "!183", "!184", "!185", "!186", "!187", "!188", "!189",
    "!190", "!191", "!192", "!193", "!194", "!195", "!196", "!197", "!198", "!199",
    "!200", "!201", "!202", "!203", "!204", "!205", "!206", "!207", "!208", "!209",
    "!210", "!211", "!212", "!213", "!214", "!215", "!216", "!217", "!218", "!219",
    "!220", "!221", "!222", "!223", "!224", "!225", "!226", "!227", "!228", "!229",
    "!230", "!231", "!232", "!233", "!234", "!235", "!236", "!237", "!238", "!239",
    "!240", "!241", "!242", "!243", "!244", "!245", "!246", "!247", "!248", "!249",
    "!250", "!251", "!252", "!253", "!254", "!255"
};

typedef struct {
    char *buf;
    size_t size;
    size_t cap;
} SixelStream;

static int
ss_append(SixelStream *ss, const char *data, size_t len)
{
    if (ss->size + len >= ss->cap) {
        size_t new_cap = ss->cap == 0 ? 16384 : ss->cap * 2;
        while (new_cap < ss->size + len + 1) {
            new_cap *= 2;
        }
        char *new_buf = (char *)PyMem_Realloc(ss->buf, new_cap);
        if (new_buf == NULL) {
            return -1;
        }
        ss->buf = new_buf;
        ss->cap = new_cap;
    }
    memcpy(ss->buf + ss->size, data, len);
    ss->size += len;
    ss->buf[ss->size] = '\0';
    return 0;
}

static int
ss_append_rle(SixelStream *ss, const char *buf, int len)
{
    int i = 0;
    while (i < len) {
        char ch = buf[i];
        int count = 1;
        while (i + count < len && buf[i + count] == ch && count < 255) {
            count++;
        }
        if (count >= 4) {
            const char *prefix = SIXEL_RLE_LOOKUP[count];
            size_t plen = strlen(prefix);
            if (ss_append(ss, prefix, plen) < 0) return -1;
            if (ss_append(ss, &ch, 1) < 0) return -1;
        } else {
            for (int j = 0; j < count; j++) {
                if (ss_append(ss, &ch, 1) < 0) return -1;
            }
        }
        i += count;
    }
    return 0;
}

static PyObject *
sixel_encode_from_bits_raw(const uint8_t *bits, int width, int height)
{
    int y;
    SixelStream ss = {NULL, 0, 0};
    PyObject *result;
    char *white_buf = NULL;
    char *black_buf = NULL;

    white_buf = (char *)PyMem_Malloc((size_t)width);
    black_buf = (char *)PyMem_Malloc((size_t)width);
    if (white_buf == NULL || black_buf == NULL) {
        if (white_buf) PyMem_Free(white_buf);
        if (black_buf) PyMem_Free(black_buf);
        return PyErr_NoMemory();
    }

    for (y = 0; y < height; y += 6) {
        int max_i = (height - y) < 6 ? (height - y) : 6;
        int x;

        Py_BEGIN_ALLOW_THREADS
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
        Py_END_ALLOW_THREADS

        /* 写入白轨: #0 + RLE(white_buf) + $ */
        if (ss_append(&ss, "#0", 2) < 0) goto oom;
        if (ss_append_rle(&ss, white_buf, width) < 0) goto oom;
        if (ss_append(&ss, "$", 1) < 0) goto oom;

        /* 写入黑轨: #1 + RLE(black_buf) + - */
        if (ss_append(&ss, "#1", 2) < 0) goto oom;
        if (ss_append_rle(&ss, black_buf, width) < 0) goto oom;
        if (ss_append(&ss, "-", 1) < 0) goto oom;
    }

    PyMem_Free(white_buf);
    PyMem_Free(black_buf);

    result = PyUnicode_FromStringAndSize(ss.buf, (Py_ssize_t)ss.size);
    if (ss.buf) PyMem_Free(ss.buf);
    return result;

oom:
    if (white_buf) PyMem_Free(white_buf);
    if (black_buf) PyMem_Free(black_buf);
    if (ss.buf) PyMem_Free(ss.buf);
    return PyErr_NoMemory();
}

static PyObject *
cimage_sixel_encode_mono(PyObject *self, PyObject *args)
{
    Py_buffer bits_buf;
    int width;
    int height;
    Py_ssize_t expected;
    const uint8_t *bits;
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
    result = sixel_encode_from_bits_raw(bits, width, height);
    PyBuffer_Release(&bits_buf);
    return result;
}

static PyObject *
cimage_matrix_to_image(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    int src_w, src_h, scale;
    const char *mode;
    int channels;
    int dst_w, dst_h;
    PyObject *out;
    const uint8_t *src;
    uint8_t *dst;
    int my, mx, dy, dx;
    uint8_t white_pixel[4];
    uint8_t black_pixel[4];

    (void)self;

    if (!PyArg_ParseTuple(args, "y*iiis", &in_buf, &src_w, &src_h, &scale, &mode)) {
        return NULL;
    }

    channels = channels_from_mode(mode);
    if (channels < 0 || channels < 3) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Only RGB and RGBA modes are supported for matrix_to_image.");
        return NULL;
    }

    if (src_w <= 0 || src_h <= 0 || scale <= 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Invalid dimensions or scale.");
        return NULL;
    }

    if (in_buf.len != (Py_ssize_t)src_w * src_h) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Matrix data length mismatch.");
        return NULL;
    }

    if (src_w > (INT_MAX / scale) || src_h > (INT_MAX / scale)) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_OverflowError, "Image size too large.");
        return NULL;
    }
    dst_w = src_w * scale;
    dst_h = src_h * scale;

    if (dst_h > 0 && dst_w > (PY_SSIZE_T_MAX / dst_h / channels)) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_OverflowError, "Allocated image size exceeds limit.");
        return NULL;
    }

    out = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)dst_w * dst_h * channels);
    if (out == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }

    src = (const uint8_t *)in_buf.buf;
    dst = (uint8_t *)PyBytes_AS_STRING(out);

    memset(white_pixel, 255, (size_t)channels);
    memset(black_pixel, 0, (size_t)channels);
    if (channels == 4) black_pixel[3] = 255;

    Py_BEGIN_ALLOW_THREADS
    if (channels == 4) {
        uint32_t wp, bp;
        memcpy(&wp, white_pixel, 4);
        memcpy(&bp, black_pixel, 4);

        for (my = 0; my < src_h; my++) {
            for (mx = 0; mx < src_w; mx++) {
                uint8_t val = src[(Py_ssize_t)my * src_w + mx];
                uint32_t p = val ? bp : wp;
                for (dy = 0; dy < scale; dy++) {
                    uint32_t *dst_row = (uint32_t *)(dst + (Py_ssize_t)(my * scale + dy) * dst_w * 4);
                    for (dx = 0; dx < scale; dx++) {
                        dst_row[mx * scale + dx] = p;
                    }
                }
            }
        }
    } else if (channels == 3) {
        for (my = 0; my < src_h; my++) {
            for (mx = 0; mx < src_w; mx++) {
                uint8_t val = src[(Py_ssize_t)my * src_w + mx];
                const uint8_t *p = val ? black_pixel : white_pixel;
                uint8_t r = p[0], g = p[1], b = p[2];
                for (dy = 0; dy < scale; dy++) {
                    uint8_t *dst_ptr = dst + ((Py_ssize_t)(my * scale + dy) * dst_w + (Py_ssize_t)mx * scale) * 3;
                    for (dx = 0; dx < scale; dx++) {
                        dst_ptr[0] = r; dst_ptr[1] = g; dst_ptr[2] = b;
                        dst_ptr += 3;
                    }
                }
            }
        }
    } else {
        for (my = 0; my < src_h; my++) {
            for (mx = 0; mx < src_w; mx++) {
                uint8_t val = src[(Py_ssize_t)my * src_w + mx];
                const uint8_t *pixel = val ? black_pixel : white_pixel;
                for (dy = 0; dy < scale; dy++) {
                    Py_ssize_t row_base = (Py_ssize_t)(my * scale + dy) * dst_w * channels;
                    for (dx = 0; dx < scale; dx++) {
                        Py_ssize_t col_base = (Py_ssize_t)(mx * scale + dx) * channels;
                        memcpy(dst + row_base + col_base, pixel, (size_t)channels);
                    }
                }
            }
        }
    }
    Py_END_ALLOW_THREADS

    PyBuffer_Release(&in_buf);
    return out;
}

static PyObject *
cimage_qr_matrix_to_luma(PyObject *self, PyObject *args)
{
    PyObject *matrix_obj;
    PyObject *rows_fast = NULL;
    PyObject *pixels = NULL;
    Py_ssize_t height;
    Py_ssize_t width;
    uint8_t *dst;
    Py_ssize_t y;

    (void)self;

    if (!PyArg_ParseTuple(args, "O", &matrix_obj)) {
        return NULL;
    }

    rows_fast = PySequence_Fast(matrix_obj, "QR matrix must be a sequence of rows.");
    if (rows_fast == NULL) {
        return NULL;
    }

    height = PySequence_Fast_GET_SIZE(rows_fast);
    if (height <= 0) {
        Py_DECREF(rows_fast);
        PyErr_SetString(PyExc_ValueError, "Generated QR matrix is empty.");
        return NULL;
    }

    {
        PyObject *first_row_obj = PySequence_Fast_GET_ITEM(rows_fast, 0);
        PyObject *first_row_fast = PySequence_Fast(first_row_obj, "QR matrix row must be a sequence.");
        if (first_row_fast == NULL) {
            Py_DECREF(rows_fast);
            return NULL;
        }
        width = PySequence_Fast_GET_SIZE(first_row_fast);
        Py_DECREF(first_row_fast);
    }

    if (width <= 0) {
        Py_DECREF(rows_fast);
        PyErr_SetString(PyExc_ValueError, "Generated QR matrix is empty.");
        return NULL;
    }
    if (height != width) {
        Py_DECREF(rows_fast);
        PyErr_SetString(PyExc_ValueError, "QR matrix must be a bool square matrix.");
        return NULL;
    }

    pixels = PyBytes_FromStringAndSize(NULL, width * height);
    if (pixels == NULL) {
        Py_DECREF(rows_fast);
        return NULL;
    }

    dst = (uint8_t *)PyBytes_AS_STRING(pixels);
    for (y = 0; y < height; y++) {
        PyObject *row_obj = PySequence_Fast_GET_ITEM(rows_fast, y);
        PyObject *row_fast = PySequence_Fast(row_obj, "QR matrix row must be a sequence.");
        Py_ssize_t x;

        if (row_fast == NULL) {
            Py_DECREF(rows_fast);
            Py_DECREF(pixels);
            return NULL;
        }
        if (PySequence_Fast_GET_SIZE(row_fast) != width) {
            Py_DECREF(row_fast);
            Py_DECREF(rows_fast);
            Py_DECREF(pixels);
            PyErr_SetString(PyExc_ValueError, "QR matrix must be a bool square matrix.");
            return NULL;
        }

        for (x = 0; x < width; x++) {
            PyObject *item = PySequence_Fast_GET_ITEM(row_fast, x);
            int dark;
            if (!PyBool_Check(item)) {
                Py_DECREF(row_fast);
                Py_DECREF(rows_fast);
                Py_DECREF(pixels);
                PyErr_SetString(PyExc_ValueError, "QR matrix must contain only bool values.");
                return NULL;
            }
            dark = (item == Py_True);
            dst[y * width + x] = dark ? 0 : 255;
        }
        Py_DECREF(row_fast);
    }

    Py_DECREF(rows_fast);
    return Py_BuildValue("(nnN)", width, height, pixels);
}

static PyObject *
cimage_otsu_threshold(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    const uint8_t *data;
    Py_ssize_t total;
    uint32_t hist[256] = {0};
    double sum_total = 0;
    double sum_bg = 0;
    uint32_t weight_bg = 0;
    uint32_t weight_fg;
    double max_between = -1.0;
    int best_threshold = 128;
    int t;
    Py_ssize_t i;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*", &in_buf)) {
        return NULL;
    }

    data = (const uint8_t *)in_buf.buf;
    total = in_buf.len;
    if (total == 0) {
        PyBuffer_Release(&in_buf);
        return PyLong_FromLong(128);
    }

    for (i = 0; i < total; i++) {
        uint8_t v = data[i];
        hist[v]++;
        sum_total += v;
    }

    for (t = 0; t < 256; t++) {
        weight_bg += hist[t];
        if (weight_bg == 0) continue;
        weight_fg = (uint32_t)total - weight_bg;
        if (weight_fg == 0) break;

        sum_bg += (double)t * hist[t];
        double mean_bg = sum_bg / weight_bg;
        double mean_fg = (sum_total - sum_bg) / weight_fg;
        double between = (double)weight_bg * (double)weight_fg * (mean_bg - mean_fg) * (mean_bg - mean_fg);

        if (between > max_between) {
            max_between = between;
            best_threshold = t;
        }
    }

    PyBuffer_Release(&in_buf);
    return PyLong_FromLong(best_threshold);
}

static PyObject *
cimage_find_black_bbox_bits(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    int width, height;
    const uint8_t *bits;
    int left, top, right, bottom;
    int y, x;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*ii", &in_buf, &width, &height)) {
        return NULL;
    }

    if (in_buf.len != (Py_ssize_t)width * height) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Bits length mismatch.");
        return NULL;
    }

    bits = (const uint8_t *)in_buf.buf;
    left = width;
    top = height;
    right = -1;
    bottom = -1;

    for (y = 0; y < height; y++) {
        int row_start = y * width;
        int row_has = 0;
        for (x = 0; x < width; x++) {
            if (bits[row_start + x]) {
                if (x < left) left = x;
                if (x > right) right = x;
                row_has = 1;
            }
        }
        if (row_has) {
            if (y < top) top = y;
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
cimage_sample_matrix_3x3(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    int width, height, size;
    int left, top, right, bottom;
    const uint8_t *bits;
    PyObject *out;
    uint8_t *dst;
    int my, mx;
    double bw, bh;
    double offsets[3] = {1.0/6.0, 1.0/2.0, 5.0/6.0};

    (void)self;

    if (!PyArg_ParseTuple(args, "y*ii(iiii)i", &in_buf, &width, &height, &left, &top, &right, &bottom, &size)) {
        return NULL;
    }

    if (in_buf.len != (Py_ssize_t)width * height) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Bits length mismatch.");
        return NULL;
    }

    bits = (const uint8_t *)in_buf.buf;
    out = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)size * size);
    if (out == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }
    dst = (uint8_t *)PyBytes_AS_STRING(out);

    bw = (double)(right - left);
    bh = (double)(bottom - top);
    if (bw < 1) bw = 1;
    if (bh < 1) bh = 1;

    for (my = 0; my < size; my++) {
        double y0 = top + (my * bh) / size;
        double y1 = top + ((my + 1) * bh) / size;
        for (mx = 0; mx < size; mx++) {
            double x0 = left + (mx * bw) / size;
            double x1 = left + ((mx + 1) * bw) / size;
            int votes = 0;
            int oy_idx, ox_idx;
            for (oy_idx = 0; oy_idx < 3; oy_idx++) {
                int py = (int)(y0 + offsets[oy_idx] * (y1 - y0));
                if (py < 0) py = 0;
                if (py >= height) py = height - 1;
                for (ox_idx = 0; ox_idx < 3; ox_idx++) {
                    int px = (int)(x0 + offsets[ox_idx] * (x1 - x0));
                    if (px < 0) px = 0;
                    if (px >= width) px = width - 1;
                    if (bits[py * width + px]) votes++;
                }
            }
            dst[my * size + mx] = (votes >= 5) ? 1 : 0;
        }
    }

    PyBuffer_Release(&in_buf);
    return out;
}

static PyObject *
cimage_estimate_module_size(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    int width, height;
    int left, top, right, bottom;
    const uint8_t *bits;
    int samples_y[5], samples_x[5];
    int run_count = 0;
    int run_cap = 256;
    int *runs;
    int i, j;
    double module_size = -1.0;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*ii(iiii)", &in_buf, &width, &height, &left, &top, &right, &bottom)) {
        return NULL;
    }

    if (in_buf.len != (Py_ssize_t)width * height) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Bits length mismatch.");
        return NULL;
    }

    if (right <= left || bottom <= top) {
        PyBuffer_Release(&in_buf);
        Py_RETURN_NONE;
    }

    bits = (const uint8_t *)in_buf.buf;
    runs = (int *)PyMem_Malloc(sizeof(int) * (size_t)run_cap);
    if (runs == NULL) {
        PyBuffer_Release(&in_buf);
        return PyErr_NoMemory();
    }

    for (i = 0; i < 5; i++) {
        samples_y[i] = top + ((bottom - top - 1) * i) / 4;
        samples_x[i] = left + ((right - left - 1) * i) / 4;
    }

    for (i = 0; i < 5; i++) {
        int y = samples_y[i];
        int row_start = y * width;
        uint8_t prev = bits[row_start + left];
        int run = 1;
        for (int x = left + 1; x < right; x++) {
            uint8_t cur = bits[row_start + x];
            if (cur == prev) {
                run++;
            } else {
                if (run_count >= run_cap) {
                    int *new_runs;
                    run_cap *= 2;
                    new_runs = (int *)PyMem_Realloc(runs, sizeof(int) * (size_t)run_cap);
                    if (new_runs == NULL) {
                        PyMem_Free(runs);
                        PyBuffer_Release(&in_buf);
                        return PyErr_NoMemory();
                    }
                    runs = new_runs;
                }
                runs[run_count++] = run;
                run = 1;
                prev = cur;
            }
        }
        if (run_count >= run_cap) {
            int *new_runs;
            run_cap *= 2;
            new_runs = (int *)PyMem_Realloc(runs, sizeof(int) * (size_t)run_cap);
            if (new_runs == NULL) {
                PyMem_Free(runs);
                PyBuffer_Release(&in_buf);
                return PyErr_NoMemory();
            }
            runs = new_runs;
        }
        runs[run_count++] = run;
    }

    for (i = 0; i < 5; i++) {
        int x = samples_x[i];
        uint8_t prev = bits[top * width + x];
        int run = 1;
        for (int y = top + 1; y < bottom; y++) {
            uint8_t cur = bits[y * width + x];
            if (cur == prev) {
                run++;
            } else {
                if (run_count >= run_cap) {
                    int *new_runs;
                    run_cap *= 2;
                    new_runs = (int *)PyMem_Realloc(runs, sizeof(int) * (size_t)run_cap);
                    if (new_runs == NULL) {
                        PyMem_Free(runs);
                        PyBuffer_Release(&in_buf);
                        return PyErr_NoMemory();
                    }
                    runs = new_runs;
                }
                runs[run_count++] = run;
                run = 1;
                prev = cur;
            }
        }
        if (run_count >= run_cap) {
            int *new_runs;
            run_cap *= 2;
            new_runs = (int *)PyMem_Realloc(runs, sizeof(int) * (size_t)run_cap);
            if (new_runs == NULL) {
                PyMem_Free(runs);
                PyBuffer_Release(&in_buf);
                return PyErr_NoMemory();
            }
            runs = new_runs;
        }
        runs[run_count++] = run;
    }

    int filtered_count = 0;
    for (i = 0; i < run_count; i++) if (runs[i] >= 2) runs[filtered_count++] = runs[i];
    if (filtered_count == 0) {
        for (i = 0; i < run_count; i++) if (runs[i] >= 1) runs[filtered_count++] = runs[i];
    }

    if (filtered_count > 0) {
        for (i = 0; i < filtered_count - 1; i++) {
            for (j = i + 1; j < filtered_count; j++) {
                if (runs[i] > runs[j]) {
                    int tmp = runs[i];
                    runs[i] = runs[j];
                    runs[j] = tmp;
                }
            }
        }
        int median_count = filtered_count / 2;
        if (median_count == 0) median_count = 1;
        int sum_lower = 0;
        for (i = 0; i < median_count; i++) sum_lower += runs[i];
        
        // Use simpler median or average of lower half
        if (median_count % 2 == 1) {
            module_size = (double)runs[median_count / 2];
        } else {
            module_size = (double)(runs[median_count / 2 - 1] + runs[median_count / 2]) / 2.0;
        }
    }

    PyMem_Free(runs);
    PyBuffer_Release(&in_buf);

    if (module_size < 1.0) {
        Py_RETURN_NONE;
    }
    return PyFloat_FromDouble(module_size);
}

typedef struct {
    double x;
    double y;
    double module;
    int count;
    int score;
} FinderCenter;

static uint8_t
bit_at(const uint8_t *bits, int width, int height, int x, int y)
{
    if (x < 0 || y < 0 || x >= width || y >= height) {
        return 0;
    }
    return bits[y * width + x] ? 1 : 0;
}

static int
ratio_match_11311(const int runs[5], double variance)
{
    double total = (double)runs[0] + runs[1] + runs[2] + runs[3] + runs[4];
    double module;
    double tol;
    if (runs[0] <= 0 || runs[1] <= 0 || runs[2] <= 0 || runs[3] <= 0 || runs[4] <= 0) {
        return 0;
    }
    if (total < 7.0) {
        return 0;
    }
    module = total / 7.0;
    tol = module * variance;
    if (fabs((double)runs[0] - module) > tol) return 0;
    if (fabs((double)runs[1] - module) > tol) return 0;
    if (fabs((double)runs[3] - module) > tol) return 0;
    if (fabs((double)runs[4] - module) > tol) return 0;
    if (fabs((double)runs[2] - 3.0 * module) > (tol * 3.0)) return 0;
    return 1;
}

static int
collect_cross_runs_horizontal(const uint8_t *bits, int width, int height, int cx, int cy, int runs[5])
{
    int x;
    int c2 = 0, c1 = 0, c0 = 0, c3 = 0, c4 = 0;
    int max_run = width / 3;
    if (!bit_at(bits, width, height, cx, cy)) return 0;

    x = cx;
    while (x >= 0 && bit_at(bits, width, height, x, cy)) {
        if (++c2 > max_run) return 0;
        x--;
    }
    while (x >= 0 && !bit_at(bits, width, height, x, cy)) {
        if (++c1 > max_run) return 0;
        x--;
    }
    while (x >= 0 && bit_at(bits, width, height, x, cy)) {
        if (++c0 > max_run) return 0;
        x--;
    }

    x = cx + 1;
    while (x < width && bit_at(bits, width, height, x, cy)) {
        if (++c2 > max_run) return 0;
        x++;
    }
    while (x < width && !bit_at(bits, width, height, x, cy)) {
        if (++c3 > max_run) return 0;
        x++;
    }
    while (x < width && bit_at(bits, width, height, x, cy)) {
        if (++c4 > max_run) return 0;
        x++;
    }

    runs[0] = c0;
    runs[1] = c1;
    runs[2] = c2;
    runs[3] = c3;
    runs[4] = c4;
    return 1;
}

static int
collect_cross_runs_vertical(const uint8_t *bits, int width, int height, int cx, int cy, int runs[5])
{
    int y;
    int c2 = 0, c1 = 0, c0 = 0, c3 = 0, c4 = 0;
    int max_run = height / 3;
    if (!bit_at(bits, width, height, cx, cy)) return 0;

    y = cy;
    while (y >= 0 && bit_at(bits, width, height, cx, y)) {
        if (++c2 > max_run) return 0;
        y--;
    }
    while (y >= 0 && !bit_at(bits, width, height, cx, y)) {
        if (++c1 > max_run) return 0;
        y--;
    }
    while (y >= 0 && bit_at(bits, width, height, cx, y)) {
        if (++c0 > max_run) return 0;
        y--;
    }

    y = cy + 1;
    while (y < height && bit_at(bits, width, height, cx, y)) {
        if (++c2 > max_run) return 0;
        y++;
    }
    while (y < height && !bit_at(bits, width, height, cx, y)) {
        if (++c3 > max_run) return 0;
        y++;
    }
    while (y < height && bit_at(bits, width, height, cx, y)) {
        if (++c4 > max_run) return 0;
        y++;
    }

    runs[0] = c0;
    runs[1] = c1;
    runs[2] = c2;
    runs[3] = c3;
    runs[4] = c4;
    return 1;
}

static int
append_or_merge_center(FinderCenter *centers, int *center_count, int center_cap, double x, double y, double module)
{
    int i;
    double merge_radius_sq = module * module * 2.56;
    for (i = 0; i < *center_count; i++) {
        double dx = centers[i].x - x;
        double dy = centers[i].y - y;
        if (dx * dx + dy * dy <= merge_radius_sq) {
            int n = centers[i].count + 1;
            centers[i].x = (centers[i].x * centers[i].count + x) / n;
            centers[i].y = (centers[i].y * centers[i].count + y) / n;
            centers[i].module = (centers[i].module * centers[i].count + module) / n;
            centers[i].count = n;
            centers[i].score += 1;
            return 0;
        }
    }
    if (*center_count >= center_cap) {
        return -1;
    }
    centers[*center_count].x = x;
    centers[*center_count].y = y;
    centers[*center_count].module = module;
    centers[*center_count].count = 1;
    centers[*center_count].score = 1;
    *center_count += 1;
    return 0;
}

static int
ensure_center_capacity(FinderCenter **centers, int *center_cap, int center_count)
{
    FinderCenter *new_centers;
    int new_cap;

    if (center_count < *center_cap) {
        return 0;
    }
    if (*center_cap > (INT_MAX / 2)) {
        PyErr_SetString(PyExc_OverflowError, "Too many finder candidates.");
        return -1;
    }

    new_cap = *center_cap * 2;
    new_centers = (FinderCenter *)PyMem_Realloc(*centers, (size_t)new_cap * sizeof(FinderCenter));
    if (new_centers == NULL) {
        PyErr_NoMemory();
        return -1;
    }

    memset(new_centers + *center_cap, 0, (size_t)(new_cap - *center_cap) * sizeof(FinderCenter));
    *centers = new_centers;
    *center_cap = new_cap;
    return 0;
}

static PyObject *
cimage_find_finder_centers(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    int width, height;
    double variance;
    const uint8_t *bits;
    FinderCenter *centers = NULL;
    int center_cap = 256;
    int center_count = 0;
    int x, y;
    int i;
    int idx_tl = -1;
    int idx_tr = -1;
    int idx_bl = -1;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*iid", &in_buf, &width, &height, &variance)) {
        return NULL;
    }
    if (width <= 0 || height <= 0 || in_buf.len != (Py_ssize_t)width * height) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Bits length mismatch.");
        return NULL;
    }
    if (variance <= 0.0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "variance must be > 0.");
        return NULL;
    }

    bits = (const uint8_t *)in_buf.buf;
    centers = (FinderCenter *)PyMem_Calloc((size_t)center_cap, sizeof(FinderCenter));
    if (centers == NULL) {
        PyBuffer_Release(&in_buf);
        return PyErr_NoMemory();
    }

    for (y = 1; y < height - 1; y += 2) {
        for (x = 1; x < width - 1; x++) {
            int hruns[5];
            int vruns[5];
            double hmodule;
            double vmodule;
            double module;
            int total;
            if (!bit_at(bits, width, height, x, y)) {
                continue;
            }
            if (!collect_cross_runs_horizontal(bits, width, height, x, y, hruns)) {
                continue;
            }
            total = hruns[0] + hruns[1] + hruns[2] + hruns[3] + hruns[4];
            if (total < 7 || hruns[2] < 3) {
                continue;
            }
            if (!ratio_match_11311(hruns, variance)) {
                continue;
            }
            if (!collect_cross_runs_vertical(bits, width, height, x, y, vruns)) {
                continue;
            }
            total = vruns[0] + vruns[1] + vruns[2] + vruns[3] + vruns[4];
            if (total < 7 || vruns[2] < 3) {
                continue;
            }
            if (!ratio_match_11311(vruns, variance)) {
                continue;
            }

            hmodule = (double)total / 7.0;
            vmodule = ((double)vruns[0] + vruns[1] + vruns[2] + vruns[3] + vruns[4]) / 7.0;
            module = (hmodule + vmodule) * 0.5;
            if (ensure_center_capacity(&centers, &center_cap, center_count) < 0) {
                PyMem_Free(centers);
                PyBuffer_Release(&in_buf);
                return NULL;
            }
            if (append_or_merge_center(centers, &center_count, center_cap, (double)x, (double)y, module) < 0) {
                PyMem_Free(centers);
                PyBuffer_Release(&in_buf);
                PyErr_SetString(PyExc_RuntimeError, "Failed to record finder candidate.");
                return NULL;
            }

            /* Optimization: skip known module width */
            x += (int)(module * 2.0);
        }
    }

    if (center_count < 3) {
        PyMem_Free(centers);
        PyBuffer_Release(&in_buf);
        Py_RETURN_NONE;
    }

    for (i = 0; i < center_count; i++) {
        if (idx_tl < 0 || (centers[i].x + centers[i].y) < (centers[idx_tl].x + centers[idx_tl].y)) {
            idx_tl = i;
        }
        if (idx_tr < 0 || (centers[i].x - centers[i].y) > (centers[idx_tr].x - centers[idx_tr].y)) {
            idx_tr = i;
        }
        if (idx_bl < 0 || (centers[i].y - centers[i].x) > (centers[idx_bl].y - centers[idx_bl].x)) {
            idx_bl = i;
        }
    }

    if (idx_tl < 0 || idx_tr < 0 || idx_bl < 0 || idx_tl == idx_tr || idx_tl == idx_bl || idx_tr == idx_bl) {
        PyMem_Free(centers);
        PyBuffer_Release(&in_buf);
        Py_RETURN_NONE;
    }

    {
        double tlx = centers[idx_tl].x;
        double tly = centers[idx_tl].y;
        double trx = centers[idx_tr].x;
        double try_ = centers[idx_tr].y;
        double blx = centers[idx_bl].x;
        double bly = centers[idx_bl].y;
        PyMem_Free(centers);
        PyBuffer_Release(&in_buf);
        return Py_BuildValue("(dddddd)", tlx, tly, trx, try_, blx, bly);
    }
}

static PyObject *
cimage_sample_matrix_affine(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    int width, height, size;
    double tlx_d, tly_d, hx_d, hy_d, vx_d, vy_d;
    int window;
    const uint8_t *bits;
    PyObject *out;
    uint8_t *dst;
    int y, x;
    int radius;
    int64_t tlx, tly, hx, hy, vx, vy;
    int64_t step;

    (void)self;

    if (!PyArg_ParseTuple(args, "y*iiiddddddi", &in_buf, &width, &height, &size, &tlx_d, &tly_d, &hx_d, &hy_d, &vx_d, &vy_d, &window)) {
        return NULL;
    }
    if (width <= 0 || height <= 0 || size <= 0 || in_buf.len != (Py_ssize_t)width * height) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "Bits length mismatch.");
        return NULL;
    }
    if (size <= 7) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "QR size must be > 7.");
        return NULL;
    }
    if (window <= 0 || (window % 2) == 0) {
        PyBuffer_Release(&in_buf);
        PyErr_SetString(PyExc_ValueError, "window must be a positive odd integer.");
        return NULL;
    }

    bits = (const uint8_t *)in_buf.buf;
    radius = window / 2;
    out = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)size * size);
    if (out == NULL) {
        PyBuffer_Release(&in_buf);
        return NULL;
    }
    dst = (uint8_t *)PyBytes_AS_STRING(out);

    /* Convert to fixed point (16.16) */
    step = (int64_t)((1.0 / ((double)size - 7.0)) * 65536.0);
    tlx = (int64_t)((tlx_d - 3.5 / ((double)size - 7.0) * hx_d - 3.5 / ((double)size - 7.0) * vx_d) * 65536.0);
    tly = (int64_t)((tly_d - 3.5 / ((double)size - 7.0) * hy_d - 3.5 / ((double)size - 7.0) * vy_d) * 65536.0);
    hx = (int64_t)(hx_d * 65536.0);
    hy = (int64_t)(hy_d * 65536.0);
    vx = (int64_t)(vx_d * 65536.0);
    vy = (int64_t)(vy_d * 65536.0);

    Py_BEGIN_ALLOW_THREADS
    for (y = 0; y < size; y++) {
        /* Line start point in fixed point */
        int64_t line_x = tlx + ((((int64_t)y * vx) * step) >> 16);
        int64_t line_y = tly + ((((int64_t)y * vy) * step) >> 16);

        for (x = 0; x < size; x++) {
            /* Current point in fixed point */
            int64_t cur_fx = line_x + ((((int64_t)x * hx) * step) >> 16);
            int64_t cur_fy = line_y + ((((int64_t)x * hy) * step) >> 16);

            /* Round to nearest integer */
            int64_t cx64 = (cur_fx + 32768) >> 16;
            int64_t cy64 = (cur_fy + 32768) >> 16;
            int cx = (cx64 < INT_MIN) ? INT_MIN : (cx64 > INT_MAX ? INT_MAX : (int)cx64);
            int cy = (cy64 < INT_MIN) ? INT_MIN : (cy64 > INT_MAX ? INT_MAX : (int)cy64);

            int yy, xx;
            int black = 0;
            int total = 0;

            for (yy = cy - radius; yy <= cy + radius; yy++) {
                int sy = yy;
                if (sy < 0) sy = 0;
                if (sy >= height) sy = height - 1;
                for (xx = cx - radius; xx <= cx + radius; xx++) {
                    int sx = xx;
                    if (sx < 0) sx = 0;
                    if (sx >= width) sx = width - 1;
                    if (bits[sy * width + sx]) {
                        black++;
                    }
                    total++;
                }
            }
            dst[y * size + x] = (black * 2 >= total) ? 1 : 0;
        }
    }
    Py_END_ALLOW_THREADS

    PyBuffer_Release(&in_buf);
    return out;
}

static PyMethodDef cimage_methods[] = {
    {"convert", cimage_convert, METH_VARARGS, "Convert image mode."},
    {"getbbox_nonwhite", cimage_getbbox_nonwhite, METH_VARARGS, "Get non-white bbox."},
    {"resize_nearest", cimage_resize_nearest, METH_VARARGS, "Nearest resize."},
    {"decode_png_8bit", cimage_decode_png_8bit, METH_VARARGS, "Decode PNG bytes via libpng."},
    {"encode_png_8bit", cimage_encode_png_8bit, METH_VARARGS, "Encode raw image to PNG via libpng."},
    {"decode_jpeg_turbo", cimage_decode_jpeg_turbo, METH_VARARGS, "Decode JPEG bytes via libturbojpeg."},
    {"decode_webp_lib", cimage_decode_webp_lib, METH_VARARGS, "Decode WEBP bytes via libwebp."},
    {"threshold_to_bits", cimage_threshold_to_bits, METH_VARARGS, "Threshold image to 0/1 bits."},
    {"sixel_encode_mono", cimage_sixel_encode_mono, METH_VARARGS, "Encode mono bits to sixel body."},
    {"matrix_to_image", cimage_matrix_to_image, METH_VARARGS, "Matrix to image pixels."},
    {"qr_matrix_to_luma", cimage_qr_matrix_to_luma, METH_VARARGS, "Convert QR bool matrix to L pixels."},
    {"otsu_threshold", cimage_otsu_threshold, METH_VARARGS, "Otsu threshold calculation."},
    {"find_black_bbox_bits", cimage_find_black_bbox_bits, METH_VARARGS, "Find black bbox in bits."},
    {"sample_matrix_3x3", cimage_sample_matrix_3x3, METH_VARARGS, "Sample QR matrix with 3x3 voting."},
    {"estimate_module_size", cimage_estimate_module_size, METH_VARARGS, "Estimate module size."},
    {"find_finder_centers", cimage_find_finder_centers, METH_VARARGS, "Find finder centers via run-length scan."},
    {"sample_matrix_affine", cimage_sample_matrix_affine, METH_VARARGS, "Sample QR matrix using affine coordinates."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef cimage_module = {
    PyModuleDef_HEAD_INIT,
    "_cimage",
    "C acceleration backend for terminal_qrcode.",
    -1,
    cimage_methods,
};

PyMODINIT_FUNC
PyInit__cimage(void)
{
    return PyModule_Create(&cimage_module);
}
