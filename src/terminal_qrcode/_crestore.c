#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <math.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static int
compare_ints(const void *a, const void *b)
{
    int lhs = *(const int *)a;
    int rhs = *(const int *)b;
    return (lhs > rhs) - (lhs < rhs);
}

static int
append_run_length(int **runs_ptr, int *run_count_ptr, int *run_cap_ptr, int run)
{
    int *new_runs;

    if (*run_count_ptr >= *run_cap_ptr) {
        int new_cap = (*run_cap_ptr < INT_MAX / 2) ? (*run_cap_ptr * 2) : INT_MAX;
        if (new_cap <= *run_cap_ptr) {
            PyErr_SetString(PyExc_OverflowError, "Too many run lengths.");
            return -1;
        }
        new_runs = (int *)PyMem_Realloc(*runs_ptr, sizeof(int) * (size_t)new_cap);
        if (new_runs == NULL) {
            PyErr_NoMemory();
            return -1;
        }
        *runs_ptr = new_runs;
        *run_cap_ptr = new_cap;
    }

    (*runs_ptr)[(*run_count_ptr)++] = run;
    return 0;
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
call_restore_impl(const char *name, PyObject *args)
{
    PyObject *module = PyImport_ImportModule("terminal_qrcode._restore");
    PyObject *callable;
    PyObject *result;

    if (module == NULL) {
        return NULL;
    }

    callable = PyObject_GetAttrString(module, name);
    Py_DECREF(module);
    if (callable == NULL) {
        return NULL;
    }

    result = PyObject_CallObject(callable, args);
    Py_DECREF(callable);
    return result;
}

static PyObject *
crestore_strict_restore_qr_matrix(PyObject *self, PyObject *args)
{
    (void)self;
    return call_restore_impl("strict_restore_qr_matrix", args);
}

static PyObject *
crestore_find_black_bbox_bits(PyObject *self, PyObject *args)
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
crestore_sample_matrix_3x3(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    int width, height, size;
    int left, top, right, bottom;
    const uint8_t *bits;
    PyObject *out;
    uint8_t *dst;
    int my, mx;
    double bw, bh;
    double offsets[3] = {1.0 / 6.0, 1.0 / 2.0, 5.0 / 6.0};

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
crestore_estimate_module_size(PyObject *self, PyObject *args)
{
    Py_buffer in_buf;
    int width, height;
    int left, top, right, bottom;
    const uint8_t *bits;
    int samples_y[5], samples_x[5];
    int run_count = 0;
    int run_cap = 256;
    int *runs;
    int i;
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
                if (append_run_length(&runs, &run_count, &run_cap, run) < 0) {
                    PyMem_Free(runs);
                    PyBuffer_Release(&in_buf);
                    return NULL;
                }
                run = 1;
                prev = cur;
            }
        }
        if (append_run_length(&runs, &run_count, &run_cap, run) < 0) {
            PyMem_Free(runs);
            PyBuffer_Release(&in_buf);
            return NULL;
        }
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
                if (append_run_length(&runs, &run_count, &run_cap, run) < 0) {
                    PyMem_Free(runs);
                    PyBuffer_Release(&in_buf);
                    return NULL;
                }
                run = 1;
                prev = cur;
            }
        }
        if (append_run_length(&runs, &run_count, &run_cap, run) < 0) {
            PyMem_Free(runs);
            PyBuffer_Release(&in_buf);
            return NULL;
        }
    }

    {
        int filtered_count = 0;

        for (i = 0; i < run_count; i++) if (runs[i] >= 2) runs[filtered_count++] = runs[i];
        if (filtered_count == 0) {
            for (i = 0; i < run_count; i++) if (runs[i] >= 1) runs[filtered_count++] = runs[i];
        }

        if (filtered_count > 0) {
            int median_count;

            qsort(runs, (size_t)filtered_count, sizeof(int), compare_ints);
            median_count = filtered_count / 2;
            if (median_count == 0) median_count = 1;
            if (median_count % 2 == 1) {
                module_size = (double)runs[median_count / 2];
            } else {
                module_size = (double)(runs[median_count / 2 - 1] + runs[median_count / 2]) / 2.0;
            }
        }
    }

    PyMem_Free(runs);
    PyBuffer_Release(&in_buf);

    if (module_size < 1.0) {
        Py_RETURN_NONE;
    }
    return PyFloat_FromDouble(module_size);
}

static PyObject *
crestore_find_finder_centers(PyObject *self, PyObject *args)
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
crestore_sample_matrix_affine(PyObject *self, PyObject *args)
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

    step = (int64_t)((1.0 / ((double)size - 7.0)) * 65536.0);
    tlx = (int64_t)((tlx_d - 3.5 / ((double)size - 7.0) * hx_d - 3.5 / ((double)size - 7.0) * vx_d) * 65536.0);
    tly = (int64_t)((tly_d - 3.5 / ((double)size - 7.0) * hy_d - 3.5 / ((double)size - 7.0) * vy_d) * 65536.0);
    hx = (int64_t)(hx_d * 65536.0);
    hy = (int64_t)(hy_d * 65536.0);
    vx = (int64_t)(vx_d * 65536.0);
    vy = (int64_t)(vy_d * 65536.0);

    Py_BEGIN_ALLOW_THREADS
    for (y = 0; y < size; y++) {
        int64_t line_x = tlx + ((((int64_t)y * vx) * step) >> 16);
        int64_t line_y = tly + ((((int64_t)y * vy) * step) >> 16);

        for (x = 0; x < size; x++) {
            int64_t cur_fx = line_x + ((((int64_t)x * hx) * step) >> 16);
            int64_t cur_fy = line_y + ((((int64_t)x * hy) * step) >> 16);
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

static PyObject *
crestore_score_finder(PyObject *self, PyObject *args)
{
    Py_buffer buf;
    int size;
    const uint8_t *matrix;
    int matches = 0;
    int total = 0;
    int origins[3][2];

    (void)self;

    if (!PyArg_ParseTuple(args, "y*i", &buf, &size)) {
        return NULL;
    }
    if (size < 21 || buf.len < (Py_ssize_t)size * size) {
        PyBuffer_Release(&buf);
        return PyFloat_FromDouble(0.0);
    }

    matrix = (const uint8_t *)buf.buf;
    origins[0][0] = 0;
    origins[0][1] = 0;
    origins[1][0] = size - 7;
    origins[1][1] = 0;
    origins[2][0] = 0;
    origins[2][1] = size - 7;

    for (int k = 0; k < 3; k++) {
        int ox = origins[k][0];
        int oy = origins[k][1];

        for (int y = 0; y < 7; y++) {
            for (int x = 0; x < 7; x++) {
                int val = matrix[(oy + y) * size + (ox + x)];
                int expected;

                if (x == 0 || x == 6 || y == 0 || y == 6) {
                    expected = 1;
                } else if (x == 1 || x == 5 || y == 1 || y == 5) {
                    expected = 0;
                } else {
                    expected = 1;
                }
                if ((val ? 1 : 0) == expected) {
                    matches++;
                }
                total++;
            }
        }
    }

    PyBuffer_Release(&buf);
    return PyFloat_FromDouble(total > 0 ? (double)matches / total : 0.0);
}

static PyMethodDef crestore_methods[] = {
    {"strict_restore_qr_matrix", crestore_strict_restore_qr_matrix, METH_VARARGS, "Strictly restore QR matrix."},
    {"find_black_bbox_bits", crestore_find_black_bbox_bits, METH_VARARGS, "Find black bbox in bits."},
    {"sample_matrix_3x3", crestore_sample_matrix_3x3, METH_VARARGS, "Sample QR matrix with 3x3 voting."},
    {"estimate_module_size", crestore_estimate_module_size, METH_VARARGS, "Estimate module size."},
    {"find_finder_centers", crestore_find_finder_centers, METH_VARARGS, "Find finder centers via run-length scan."},
    {"sample_matrix_affine", crestore_sample_matrix_affine, METH_VARARGS, "Sample QR matrix using affine coordinates."},
    {"score_finder", crestore_score_finder, METH_VARARGS, "Calculate finder score for a matrix."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef crestore_module = {
    PyModuleDef_HEAD_INIT,
    "_crestore",
    "C QR restore entrypoint for terminal_qrcode.",
    -1,
    crestore_methods,
};

PyMODINIT_FUNC
PyInit__crestore(void)
{
    return PyModule_Create(&crestore_module);
}
