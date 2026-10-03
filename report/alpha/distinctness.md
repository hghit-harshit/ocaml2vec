| vocabulary | Cload_* | Cstore_* | Lapply_a* | Lfunction_a* | Pgetglobal_* | operand_kinds | types | low-conf. movement / rest | low-conf. cohesion |
|---|---|---|---|---|---|---|---|---|---|
| lambda.complex a=1.0 | - | - | 0.530 | 0.372 | 0.270 | 0.688 | 0.826 | 4.51 / 4.69 | 0.516 |
| lambda.complex a=0.75 | - | - | 0.516 | 0.341 | 0.262 | 0.633 | 0.645 | 4.64 / 4.86 | 0.690 |
| lambda.transe a=1.0 | - | - | 0.502 | 0.708 | 0.914 | 0.770 | 0.854 | 0.71 / 0.84 | 1.005 |
| lambda.transe a=0.75 | - | - | 0.555 | 0.731 | 0.726 | 0.754 | 0.802 | 0.95 / 1.00 | 0.991 |
| cmm.complex a=1.0 | 0.652 | 0.362 | - | - | - | 0.909 | 0.966 | 3.67 / 3.64 | 0.344 |
| cmm.complex a=0.75 | 0.632 | 0.405 | - | - | - | 0.811 | 0.847 | 3.67 / 3.64 | 0.469 |
| cmm.transe a=1.0 | 0.914 | 0.944 | - | - | - | 0.824 | 0.885 | 0.75 / 0.81 | 0.976 |
| cmm.transe a=0.75 | 0.913 | 0.924 | - | - | - | 0.830 | 0.896 | 0.79 / 0.84 | 0.982 |

lambda.complex a=1.0: rare families (movement; nearest neighbours; # low-confidence among them)
  Pperform: movement 4.36; Pbytes_of_string 0.85, Patomic_load 0.84, Preperform 0.82, Pcompare_floats 0.78, Pcvtbint 0.78; 5/5
  Presume: movement 4.47; Prunstack 0.84, Preperform 0.80, Pdls_get 0.78, Patomic_load 0.77, Pperform 0.75; 5/5
  Prunstack: movement 4.53; Preperform 0.88, Presume 0.84, Patomic_load 0.82, Pdls_get 0.82, Pxorint 0.80; 5/5
  Preperform: movement 5.01; Prunstack 0.88, Patomic_load 0.85, Pbytes_of_string 0.85, Pperform 0.82, Presume 0.80; 5/5
  Patomic_load: movement 4.60; Pbytes_of_string 0.89, Pdls_get 0.89, Pasrbint 0.86, Preperform 0.85, Pctconst 0.85; 5/5
  Pdls_get: movement 4.80; Pctconst 0.94, Patomic_load 0.89, Pbytes_of_string 0.84, Prunstack 0.82, Pmodbint 0.80; 5/5

lambda.complex a=0.75: rare families (movement; nearest neighbours; # low-confidence among them)
  Pperform: movement 4.30; Patomic_load 0.78, Pbytes_of_string 0.78, Preperform 0.77, Poffsetref 0.70, Pdls_get 0.68; 5/5
  Presume: movement 5.01; Prunstack 0.67, Preperform 0.63, Pdls_get 0.62, Pperform 0.58, ADDR 0.57; 4/5
  Prunstack: movement 4.72; Preperform 0.76, Pdls_get 0.73, Patomic_load 0.68, Presume 0.67, Pctconst 0.66; 5/5
  Preperform: movement 5.02; Patomic_load 0.78, Pbytes_of_string 0.77, Pperform 0.77, Prunstack 0.76, Pcompare_bints 0.75; 5/5
  Patomic_load: movement 4.55; Pbytes_of_string 0.82, Pdls_get 0.80, Pperform 0.78, Preperform 0.78, Pasrbint 0.76; 5/5
  Pdls_get: movement 4.69; Pctconst 0.91, Patomic_load 0.80, Prunstack 0.73, Preperform 0.73, Pbytes_of_string 0.73; 5/5

lambda.transe a=1.0: rare families (movement; nearest neighbours; # low-confidence among them)
  Pperform: movement 0.61; Presume 0.17, VAR_BINT 0.17, GEN 0.16, Poffsetref 0.16, Pbytes_of_string 0.15; 3/5
  Presume: movement 0.62; Porbint 0.22, Preperform 0.19, Pperform 0.17, BINT 0.15, Pstringrefu 0.15; 4/5
  Prunstack: movement 0.68; Pcvtbint 0.23, Preperform 0.20, Pdls_get 0.17, GEN 0.17, Pisout 0.15; 3/5
  Preperform: movement 0.71; Pasrbint 0.21, Prunstack 0.20, Presume 0.19, Pctconst 0.13, Pisint 0.12; 4/5
  Patomic_load: movement 0.76; Pasrint 0.19, MUTVAR 0.15, Pstringrefu 0.14, Pbytesrefu 0.13, Pbytes_of_string 0.12; 4/5
  Pdls_get: movement 0.83; Pbytes_to_string 0.23, Pbytessetu 0.22, Pasrbint 0.17, Prunstack 0.17, GEN 0.16; 4/5

lambda.transe a=0.75: rare families (movement; nearest neighbours; # low-confidence among them)
  Pperform: movement 0.94; CONST_BINT 0.20, GEN 0.17, CONST_STRING 0.16, INT 0.15, P_BSWAP 0.14; 2/5
  Presume: movement 0.95; CONST_BLOCK 0.17, Porbint 0.17, FLOAT 0.15, Pdls_get 0.14, Preperform 0.13; 3/5
  Prunstack: movement 0.96; GEN 0.24, Preperform 0.23, Pctconst 0.18, Pdls_get 0.15, Pisout 0.15; 3/5
  Preperform: movement 0.98; Prunstack 0.23, INT 0.21, Pisint 0.16, Lstringswitch 0.16, Presume 0.13; 2/5
  Patomic_load: movement 0.93; Pabsfloat 0.14, Pctconst 0.14, Pasrint 0.12, Pbytes_of_string 0.12, Pmodbint 0.12; 5/5
  Pdls_get: movement 0.97; GEN 0.28, Pbytessetu 0.20, CONST_INT 0.20, Pctconst 0.19, Pfloatofint 0.17; 3/5

cmm.complex a=1.0: rare families (movement; nearest neighbours; # low-confidence among them)
  C_RUNTIME: movement 3.60; Cstore_byte_s 0.92, Cabsf 0.85, Cload_64 0.85, Cload_32u 0.84, Cload_16u 0.84; 5/5
  Cstore_byte_s: movement 3.52; C_RUNTIME 0.92, Cload_64 0.86, Cload_32u 0.85, Cabsf 0.85, Cload_16u 0.83; 5/5

cmm.complex a=0.75: rare families (movement; nearest neighbours; # low-confidence among them)
  C_RUNTIME: movement 3.40; Cstore_byte_s 0.81, Cabsf 0.73, Cload_32u 0.71, Cload_64 0.70, Cload_16u 0.68; 5/5
  Cstore_byte_s: movement 3.50; Cload_32u 0.82, Cstore_narrow 0.81, C_RUNTIME 0.81, Cload_64 0.80, Cload_16u 0.76; 4/5

cmm.transe a=1.0: rare families (movement; nearest neighbours; # low-confidence among them)
  C_RUNTIME: movement 0.62; Cdivi 0.24, Cabsf 0.19, INT 0.18, VAR_FLOAT 0.17, Cstore_narrow 0.13; 2/5
  Cstore_byte_s: movement 0.72; SYM_EXTERN 0.26, SYM_FUNC 0.16, Cstore_narrow 0.16, Craise 0.14, VAL 0.14; 0/5

cmm.transe a=0.75: rare families (movement; nearest neighbours; # low-confidence among them)
  C_RUNTIME: movement 0.75; Cdivi 0.24, Cstore_byte_s 0.14, Caddv 0.12, Csubf 0.11, Cabsf 0.10; 3/5
  Cstore_byte_s: movement 0.72; Cstore_narrow 0.22, Cload_16u 0.19, SYM_EXTERN 0.15, Cload_64 0.14, C_RUNTIME 0.14; 3/5
