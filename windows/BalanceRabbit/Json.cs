using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace BalanceRabbit
{
    /// <summary>
    /// 极简 JSON 解析器（parse-only）。返回 Dictionary&lt;string, object&gt;、
    /// List&lt;object&gt;、string、double、bool、null。够用且不依赖额外程序集。
    /// </summary>
    public static class Json
    {
        public static object Parse(string text)
        {
            if (text == null) throw new JsonException("empty input");
            int index = 0;
            object value = ParseValue(text, ref index);
            SkipWhitespace(text, ref index);
            if (index < text.Length)
                throw new JsonException("trailing characters at " + index);
            return value;
        }

        private static object ParseValue(string s, ref int i)
        {
            SkipWhitespace(s, ref i);
            if (i >= s.Length) throw new JsonException("unexpected end");
            char c = s[i];
            switch (c)
            {
                case '{': return ParseObject(s, ref i);
                case '[': return ParseArray(s, ref i);
                case '"': return ParseString(s, ref i);
                case 't':
                    Expect(s, ref i, "true");
                    return true;
                case 'f':
                    Expect(s, ref i, "false");
                    return false;
                case 'n':
                    Expect(s, ref i, "null");
                    return null;
                default:
                    return ParseNumber(s, ref i);
            }
        }

        private static Dictionary<string, object> ParseObject(string s, ref int i)
        {
            var result = new Dictionary<string, object>(StringComparer.Ordinal);
            i++; // '{'
            SkipWhitespace(s, ref i);
            if (i < s.Length && s[i] == '}') { i++; return result; }
            while (true)
            {
                SkipWhitespace(s, ref i);
                if (i >= s.Length || s[i] != '"') throw new JsonException("expected key at " + i);
                string key = ParseString(s, ref i);
                SkipWhitespace(s, ref i);
                if (i >= s.Length || s[i] != ':') throw new JsonException("expected ':' at " + i);
                i++;
                result[key] = ParseValue(s, ref i);
                SkipWhitespace(s, ref i);
                if (i >= s.Length) throw new JsonException("unexpected end in object");
                char c = s[i++];
                if (c == '}') return result;
                if (c != ',') throw new JsonException("expected ',' or '}' at " + (i - 1));
            }
        }

        private static List<object> ParseArray(string s, ref int i)
        {
            var result = new List<object>();
            i++; // '['
            SkipWhitespace(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return result; }
            while (true)
            {
                result.Add(ParseValue(s, ref i));
                SkipWhitespace(s, ref i);
                if (i >= s.Length) throw new JsonException("unexpected end in array");
                char c = s[i++];
                if (c == ']') return result;
                if (c != ',') throw new JsonException("expected ',' or ']' at " + (i - 1));
            }
        }

        private static string ParseString(string s, ref int i)
        {
            i++; // opening quote
            var sb = new StringBuilder();
            while (i < s.Length)
            {
                char c = s[i++];
                if (c == '"') return sb.ToString();
                if (c != '\\') { sb.Append(c); continue; }
                if (i >= s.Length) throw new JsonException("unexpected end in string");
                char esc = s[i++];
                switch (esc)
                {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (i + 4 > s.Length) throw new JsonException("bad unicode escape");
                        sb.Append((char)int.Parse(s.Substring(i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                        i += 4;
                        break;
                    default: throw new JsonException("bad escape \\" + esc);
                }
            }
            throw new JsonException("unterminated string");
        }

        private static object ParseNumber(string s, ref int i)
        {
            int start = i;
            if (i < s.Length && (s[i] == '-' || s[i] == '+')) i++;
            while (i < s.Length && (char.IsDigit(s[i]) || s[i] == '.' || s[i] == 'e' || s[i] == 'E' || s[i] == '+' || s[i] == '-')) i++;
            string token = s.Substring(start, i - start);
            double d;
            if (!double.TryParse(token, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                throw new JsonException("bad number '" + token + "'");
            return d;
        }

        private static void Expect(string s, ref int i, string token)
        {
            if (i + token.Length > s.Length || string.CompareOrdinal(s, i, token, 0, token.Length) != 0)
                throw new JsonException("expected " + token + " at " + i);
            i += token.Length;
        }

        private static void SkipWhitespace(string s, ref int i)
        {
            while (i < s.Length && (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n')) i++;
        }
    }

    public sealed class JsonException : Exception
    {
        public JsonException(string message) : base(message) { }
    }

    /// <summary>JSON 取值辅助。</summary>
    public static class JsonHelp
    {
        public static Dictionary<string, object> AsObject(object value)
        {
            return value as Dictionary<string, object>;
        }

        public static List<object> AsArray(object value)
        {
            return value as List<object>;
        }

        public static string GetString(Dictionary<string, object> obj, string key)
        {
            object value;
            if (obj == null || !obj.TryGetValue(key, out value) || value == null) return null;
            return value as string;
        }

        public static double? GetDouble(Dictionary<string, object> obj, string key)
        {
            object value;
            if (obj == null || !obj.TryGetValue(key, out value) || value == null) return null;
            if (value is double) return (double)value;
            double d;
            if (value is string && double.TryParse((string)value, NumberStyles.Float, CultureInfo.InvariantCulture, out d)) return d;
            return null;
        }

        public static bool? GetBool(Dictionary<string, object> obj, string key)
        {
            object value;
            if (obj == null || !obj.TryGetValue(key, out value) || value == null) return null;
            if (value is bool) return (bool)value;
            return null;
        }

        public static int? GetInt(Dictionary<string, object> obj, string key)
        {
            double? d = GetDouble(obj, key);
            if (!d.HasValue) return null;
            return (int)Math.Round(d.Value);
        }
    }
}
