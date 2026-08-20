# Third-party structure data

`third_party/makemeahanzi` is an unmodified shallow checkout of
[Make Me a Hanzi](https://github.com/skishore/makemeahanzi). InkStruct reads:

- `dictionary.txt`, distributed under LGPL-3.0-or-later;
- `graphics.txt`, distributed under the Arphic Public License.

The source commit and original paths are recorded in every generated structure
database. The upstream `COPYING`, `LGPL`, and `APL` license texts remain with the
checkout. HanziVG and AnimCJK are cross-check candidates and are not currently
vendored or silently mixed into the primary database.
