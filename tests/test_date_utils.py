import unittest

from modules.date_utils import parse_decimal_br


class ParseDecimalBrTests(unittest.TestCase):
    def test_interpreta_milhar_sem_virgula(self):
        self.assertEqual(parse_decimal_br("1.200"), 1200.0)

    def test_interpreta_milhar_e_decimal(self):
        self.assertEqual(parse_decimal_br("1.200,50"), 1200.5)

    def test_interpreta_decimal_com_virgula(self):
        self.assertEqual(parse_decimal_br("1200,50"), 1200.5)

    def test_preserva_decimal_com_uma_ou_duas_casas(self):
        self.assertEqual(parse_decimal_br("1.2"), 1.2)
        self.assertEqual(parse_decimal_br("1.25"), 1.25)

    def test_rejeita_formatos_ambiguos_ou_invalidos(self):
        for valor in ("1.20.0", "1.20,50", "1,2,3", "abc"):
            with self.subTest(valor=valor):
                with self.assertRaises(ValueError):
                    parse_decimal_br(valor)


if __name__ == "__main__":
    unittest.main()
