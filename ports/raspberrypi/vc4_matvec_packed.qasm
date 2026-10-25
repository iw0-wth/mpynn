# Packed multi-tile FP32 matvec for VC4.
# Derived from vc4_matvec_multitile_experimental.qasm.
# One launch assigns several 16-row tiles to each QPU; weights use TMU0,
# shared input vector uses TMU1 so the uniform FIFO is not reread per tile.
# FP32 weights are Wp[tile][k][lane]: lane offset = lane * 4 bytes,
# k stride = 16 * 4 = 64 bytes. Shared X advances by 4 bytes per k.
# Uniforms per QPU (unchanged, including tile-group strides):
#   [0] W_base (first tile)
#   [1] Y_base (first tile)
#   [2] IN_DIM
#   [3] QPU_NUM
#   [4] TILE_COUNT
#   [5] W_TILE_STRIDE bytes
#   [6] Y_TILE_STRIDE bytes
#   [7] shared X base bus address

mov rb0, unif           # W base
mov rb1, unif           # Y base
mov ra3, unif           # IN_DIM
mov ra5, unif           # QPU_NUM
mov ra6, unif           # TILE_COUNT
mov rb2, unif           # W_TILE_STRIDE
mov rb3, unif           # Y_TILE_STRIDE
mov rb4, unif           # shared X base

# Per-lane weight base offset and per-QPU VPM/DMA setup.
nop
mov r0, ra5
shl r0, r0, 7
mov r1, vdw_setup_0(1, 16, dma_h32(0, 0))
add ra8, r0, r1
mov r1, vpm_setup(1, 1, h32(0))
add ra7, ra5, r1
mov rb6, 64             # packed weight stride between successive k values

:tile_loop
mov ra20, 0
mov rb5, rb4            # reset shared-input pointer for each tile
mov r0, elem_num
shl r0, r0, 2           # packed lane offset = lane * sizeof(float)
add ra10, rb0, r0

# Prefetch k=0 for both TMUs. All SIMD lanes read the same X address.
mov r2, 4
mov tmu0_s, ra10
mov tmu1_s, rb5
add ra10, ra10, rb6
add rb5, rb5, r2

mov r1, ra3
sub.setf r1, r1, 1
mov ra31, r1
brr.allz -, :tile_epilogue
nop
nop
nop

:k_loop
# Prefetch next W and X, then consume the previous pair.
mov tmu0_s, ra10
mov tmu1_s, rb5
add ra10, ra10, rb6
add rb5, rb5, r2
ldtmu0
mov r3, r4
ldtmu1
fmul r0, r3, r4
fadd ra20, ra20, r0
sub.setf ra31, ra31, 1
brr.anynz -, :k_loop
nop
nop
nop

:tile_epilogue
ldtmu0
mov r3, r4
ldtmu1
fmul r0, r3, r4
fadd ra20, ra20, r0

# Write this tile's 16 rows.
mov vw_setup, ra7
mov vpm, ra20
mov -, vw_wait
mov vw_setup, ra8
mov vw_addr, rb1
mov -, vw_wait

# Advance to next tile and loop if any remain.
mov r0, rb2
add rb0, rb0, r0
mov r0, rb3
add rb1, rb1, r0
sub.setf ra6, ra6, 1
brr.anynz -, :tile_loop
nop
nop
nop

thrend
mov interrupt, 1
nop
