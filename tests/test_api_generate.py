"""对外 generate API 测试."""

from unittest.mock import MagicMock, patch

import pytest

from terminal_qrcode import generate


def test_generate_delegates_to_qrcode_and_draw():
    """验证 generate 正确委托给 qrcode 库并最终调用渲染流程."""
    # Mock qrcode 及其产生的矩阵
    mock_matrix = [[True, False], [False, True]]

    with patch("qrcode.QRCode") as mock_qr_class:
        mock_qr_instance = MagicMock()
        mock_qr_instance.get_matrix.return_value = mock_matrix
        mock_qr_class.return_value = mock_qr_instance

        # 调用 generate，使用 halfblock 以简化输出验证
        # 由于我们只验证委托逻辑，可以 mock 掉底层渲染
        with patch("terminal_qrcode.core.run_pipeline") as mock_pipeline:
            mock_pipeline.return_value = ["chunk1", "chunk2"]

            output = generate("test data", renderer="halfblock", error_correction="high", version=5)

            # 验证 qrcode 初始化参数
            mock_qr_class.assert_called_once()
            args, kwargs = mock_qr_class.call_args
            assert kwargs["version"] == 5
            import qrcode

            assert kwargs["error_correction"] == qrcode.constants.ERROR_CORRECT_H
            assert kwargs["border"] == 0

            # 验证数据添加
            mock_qr_instance.add_data.assert_called_once_with("test data")

            # 验证最终输出了 mock 的内容
            assert "".join(output) == "chunk1chunk2"


@pytest.mark.parametrize(
    "level,expected_const",
    [
        ("low", 1),  # ERROR_CORRECT_L
        ("medium", 0),  # ERROR_CORRECT_M
        ("quartile", 3),  # ERROR_CORRECT_Q
        ("high", 2),  # ERROR_CORRECT_H
    ],
)
def test_generate_error_correction_mapping(level, expected_const):
    """验证纠错等级字符串正确映射到 qrcode 常量."""
    with patch("qrcode.QRCode") as mock_qr_class:
        mock_qr_instance = MagicMock()
        mock_qr_instance.get_matrix.return_value = [[True]]
        mock_qr_class.return_value = mock_qr_instance

        with patch("terminal_qrcode.core.run_pipeline") as mock_pipeline:
            mock_pipeline.return_value = []
            generate("data", error_correction=level)

            _, kwargs = mock_qr_class.call_args
            assert kwargs["error_correction"] == expected_const
