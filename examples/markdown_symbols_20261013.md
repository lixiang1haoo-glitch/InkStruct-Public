# 新符号混排验证

数字与小数点 12.50 0.25 123.456

普通括号 $(12.50+0.25)=12.75$ 与关系符 $1<2\leq3\neq4$ 保留实际笔迹

## 运算与分式

$$
12.50\pm0.25\quad 3\times4=12\quad 12\div3=4
$$

$$
\frac{12.50+0.25}{3}=4.25\quad \sqrt{16}=4\quad \sqrt[3]{8}=2
$$

## 上下限与定界符

以下仅检查符号与结构的排版

$$
\sum_{1}^{5}2\quad \prod_{1}^{3}2\quad \int_{0}^{1}2\quad \oint 2
$$

$$
\left(\frac{1}{2}\right)^2=0.25\quad [1+2]=3\quad \{1,2,3\}
$$

## 集合与箭头

$$
1\in\{1,2\}\quad 3\notin\{1,2\}\quad \emptyset\subset\{1\}
$$

$$
1\rightarrow2\Rightarrow3\quad 1\leftrightarrow2\quad 0\approx0.001
$$

## 矩阵与对齐

$$
\begin{pmatrix}1&2\\3&4\end{pmatrix}
\quad
\begin{cases}2^2&1<2\\\frac{12}{3}&2\geq1\end{cases}
$$

$$
\begin{aligned}12.50+0.25&=12.75\\\frac{12.75}{3}&=4.25\end{aligned}
$$

## 表格内混排

| 序号 | 计算过程 | 数值 |
| --- | --- | ---: |
| 1 | $12.50\pm0.25$ | 12.50 |
| 2 | $\frac{12.75}{3}$ | 4.25 |
| 3 | $\sqrt{16}$ | 4.00 |

> 原始字形不做平滑和重绘

- [x] 数字及符号样本已接入
- [ ] 英文字母与希腊字母仍需补录

