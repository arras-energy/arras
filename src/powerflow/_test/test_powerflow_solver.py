"""`powerflow.solver`: the three-phase network and the PYPOWER calls"""
# pylint: disable=missing-function-docstring,invalid-name

import numpy as np
import pytest

from powerflow.solver import Network, SolverError, solve, nominal, branch_currents, dc_branch_power

VB = 2401.7771

def feeder(Z, loads, btype="PQ", delta=None, current=None, shunt=None):
    """Swing node and one node through a branch of impedance `Z`"""
    net = Network()
    src = [net.add_bus(f"s.{x}", VB, nominal(VB, k), "REF") for k, x in enumerate("ABC")]
    dst = [net.add_bus(f"d.{x}", VB, nominal(VB, k), btype) for k, x in enumerate("ABC")]
    Y = np.linalg.inv(Z)
    net.add_branch(src, dst, Y, -Y, -Y, Y)
    for k in range(3):
        net.add_wye_load(dst[k], S=loads[k], I=(current or (0, 0, 0))[k], Y=(shunt or (0, 0, 0))[k], vnom=nominal(VB, k))
    if delta:
        for k, (a, b) in enumerate(((0, 1), (1, 2), (2, 0))):
            net.add_delta_load(dst[a], dst[b], S=delta[k])
    return net, src, dst

Z = np.array([[0.3465+1.0179j, 0.1560+0.5017j, 0.1580+0.4236j],
              [0.1560+0.5017j, 0.3375+1.0478j, 0.1535+0.3849j],
              [0.1580+0.4236j, 0.1535+0.3849j, 0.3414+1.0348j]])

def fixed_point(Zm, wye=(0, 0, 0), delta=(0, 0, 0), current=(0, 0, 0), shunt=(0, 0, 0)):
    """Independent solution: V = Vs - Z I(V)"""
    vn = np.array([nominal(VB, k) for k in range(3)])
    V = vn.copy()
    for _ in range(1000):
        I = np.conj(np.array(wye)/V) + np.array(shunt)*V
        I += np.conj(vn*np.conj(np.array(current))*np.abs(V)/(V*VB))
        for k, (a, b) in enumerate(((0, 1), (1, 2), (2, 0))):
            Iab = np.conj(delta[k]/(V[a]-V[b]))
            I[a] += Iab
            I[b] -= Iab
        V = vn - Zm @ I
    return V

LOADS = (300e3+150e3j, 100e3+50e3j, 200e3+100e3j)

@pytest.mark.parametrize("method", ["NR", "FD_XB", "FD_BX"])
def test_unbalanced_wye(method):
    """Unbalanced constant-power loads through a coupled line give the
    voltages of an independent fixed-point solution"""
    net, _, dst = feeder(Z, LOADS)
    result = solve(net, method)
    assert result.success and result.calls == 1
    assert np.max(np.abs(result.V[dst] - fixed_point(Z, wye=LOADS))) < 1e-4

@pytest.mark.parametrize("method", ["NR", "FD_XB"])
def test_zip_and_delta(method):
    """Constant current, constant impedance, and delta loads"""
    delta = (50e3+20e3j, 0, 80e3+10e3j)
    current = (10+5j, 20, 0)
    shunt = (0, 0.01+0.002j, 0.005)
    net, _, dst = feeder(Z, LOADS, delta=delta, current=current, shunt=shunt)
    result = solve(net, method)
    assert result.success and result.calls > 1
    expected = fixed_point(Z, wye=LOADS, delta=delta, current=current, shunt=shunt)
    assert np.max(np.abs(result.V[dst] - expected)) < 1e-4

def test_branch_currents_balance():
    """Series currents are equal at both ends; power in minus power out is
    the I^2 Z loss"""
    net, src, dst = feeder(Z, LOADS)
    V = solve(net).V
    (i_in, i_out), = branch_currents(net, V)
    assert np.allclose(i_in, i_out)
    loss = (V[src]*np.conj(i_in)).sum() - (V[dst]*np.conj(i_out)).sum()
    assert abs(loss - i_in @ Z @ np.conj(i_in)) < 1e-6*abs(loss)
    assert np.allclose(V[dst]*np.conj(i_out), LOADS, atol=1e-2)

def test_pv_bus():
    """A PV bus keeps its voltage magnitude"""
    net, _, dst = feeder(Z, (-100e3, -100e3, -100e3), btype="PV")
    result = solve(net)
    assert result.success
    assert np.allclose(np.abs(result.V[dst]), VB)

def test_dc():
    """DC: magnitudes stay, angles follow the self reactances, flows are
    the loads"""
    net, src, dst = feeder(Z, LOADS)
    result = solve(net, "DC")
    assert result.success
    assert np.allclose(np.abs(result.V), VB)
    xpu = Z.diagonal().imag*1e6/VB**2
    expected = np.array([nominal(VB, k) for k in range(3)])
    angles = np.angle(expected) - np.array(LOADS).real/1e6*xpu
    assert np.allclose(np.angle(result.V[dst]), angles)
    flows, = dc_branch_power(net, result.V)
    assert np.allclose(flows, np.array(LOADS).real)
    assert src == [0, 1, 2]

def test_mesh():
    """Two parallel paths share the flow in inverse proportion to their
    impedances"""
    net = Network()
    src = [net.add_bus(f"s.{x}", VB, nominal(VB, k), "REF") for k, x in enumerate("ABC")]
    dst = [net.add_bus(f"d.{x}", VB, nominal(VB, k)) for k, x in enumerate("ABC")]
    for scale in (1, 2):
        Y = np.linalg.inv(Z*scale)
        net.add_branch(src, dst, Y, -Y, -Y, Y)
    for k in range(3):
        net.add_wye_load(dst[k], S=LOADS[k])
    result = solve(net)
    one, two = branch_currents(net, result.V)
    assert np.allclose(one[0], 2*two[0])
    assert np.max(np.abs(result.V[dst] - fixed_point(Z*2/3, wye=LOADS))) < 1e-4

def test_missing_phase():
    """A branch on phases A and C only"""
    net = Network()
    src = [net.add_bus(f"s.{x}", VB, nominal(VB, k), "REF") for k, x in enumerate("ABC")]
    a = net.add_bus("d.A", VB, nominal(VB, 0))
    c = net.add_bus("d.C", VB, nominal(VB, 2))
    sub = Z[np.ix_([0, 2], [0, 2])]
    Y = np.zeros((3, 3), dtype=complex)
    Y[np.ix_([0, 2], [0, 2])] = np.linalg.inv(sub)
    net.add_branch(src, (a, -1, c), Y, -Y, -Y, Y)
    net.add_wye_load(a, S=LOADS[0])
    net.add_wye_load(c, S=LOADS[2])
    result = solve(net)
    vn = np.array([nominal(VB, 0), nominal(VB, 2)])
    V = vn.copy()
    for _ in range(500):
        V = vn - sub @ np.conj(np.array([LOADS[0], LOADS[2]])/V)
    assert np.max(np.abs(result.V[[a, c]] - V)) < 1e-4

def test_errors():
    net = Network()
    with pytest.raises(SolverError, match="base voltage"):
        net.add_bus("x", 0, 1)
    with pytest.raises(SolverError, match="type 'XX'"):
        net.add_bus("x", 1, 1, "XX")
    a = net.add_bus("a", 1, 1, "PQ")
    with pytest.raises(SolverError, match="no swing bus found for a"):
        solve(net)
    with pytest.raises(SolverError, match="solver method 'GS'"):
        solve(net, "GS")
    assert solve(Network()).success and a == 0

def test_non_convergence():
    """A load beyond the transfer limit does not converge"""
    net, _, _ = feeder(Z, (50e6, 50e6, 50e6))
    result = solve(net, max_it=20)
    assert not result.success and "did not converge" in result.message

def test_all_reference():
    net = Network()
    net.add_bus("a", 1, 1, "REF")
    result = solve(net)
    assert result.success and result.V[0] == 1
