import numpy as np
import pytest
from PIL import Image, ImageDraw
from scipy.ndimage import map_coordinates
from geometry import estimate, matrix, warp


def grid(w=800, h=600):
    im = Image.new('RGB', (w, h), (190, 195, 200))
    draw = ImageDraw.Draw(im)
    for x in range(100, w, 100):
        draw.line((x, 20, x, h-20), fill=(30, 40, 50), width=3)
    for y in range(100, h, 100):
        draw.line((20, y, w-20, y), fill=(30, 40, 50), width=3)
    return np.asarray(im, dtype=np.float32) / 255


def distort(a, angle=0, vertical=0, horizontal=0):
    # Synthesize an observed scene from a known correcting homography.
    h, w = a.shape[:2]
    radius = np.hypot(w-1, h-1)/2
    y, x = np.indices((h,w), dtype=float)
    points = np.stack([(x-(w-1)/2)/radius, (y-(h-1)/2)/radius, np.ones_like(x)])
    mapped = np.einsum('ij,jhw->ihw', matrix(angle,vertical,horizontal), points)
    coords = [mapped[1]/mapped[2]*radius+(h-1)/2, mapped[0]/mapped[2]*radius+(w-1)/2]
    return np.stack([map_coordinates(a[...,ch], coords, order=1, mode='constant', cval=.76) for ch in range(3)],axis=-1)


@pytest.mark.parametrize('angle,v,h', [(3,30,0),(-4,-25,15),(0,0,-35),(0,0,0)])
def test_upright_recovers_known_geometry(angle,v,h):
    result=estimate(distort(grid(),angle,v,h), perspective=True)
    assert result['perspective'], result
    assert abs(result['angle']-angle)<.4, result
    assert abs(result['vertical']-v)<2, result
    assert abs(result['horizontal']-h)<2, result


def test_no_lines_and_noise_leave_geometry_untouched():
    for a in [np.ones((300,400,3),np.float32),np.random.default_rng(42).random((300,400,3))]:
        assert estimate(a, perspective=True)['angle'] is None


def test_warp_is_resolution_independent_and_has_no_empty_border():
    a=grid()
    for distortion in (-100, -40, 40, 100):
        out=warp(np.ones_like(a), 12, 35, -20, distortion)
        assert np.isfinite(out).all() and out.min()==1
        small=warp(a[::2,::2],12,35,-20,distortion)
        full=warp(a,12,35,-20,distortion)
        assert abs(full.shape[0]-2*small.shape[0])<=2
        assert abs(full.shape[1]-2*small.shape[1])<=2
        assert not np.allclose(full.mean(),0)


def test_lens_correction_reduces_curvature():
    # Observed coordinates satisfy x_d = x_u (1 + k*r_u^2).
    # Invert that mapping to synthesize barrel distortion independently.
    a=grid();h,w=a.shape[:2];r=np.hypot(w-1,h-1)/2
    yy,xx=np.indices((h,w));xd=(xx-(w-1)/2)/r;yd=(yy-(h-1)/2)/r
    xu,yu=xd.copy(),yd.copy();k=.2
    for _ in range(30):
        factor=1+k*(xu*xu+yu*yu);xu=xd/factor;yu=yd/factor
    coords=[yu*r+(h-1)/2,xu*r+(w-1)/2]
    observed=np.stack([map_coordinates(a[...,ch],coords,order=1) for ch in range(3)],axis=-1)
    corrected=warp(observed,distortion=60)
    ch,cw=corrected.shape[:2]
    y0,x0=(h-ch)//2,(w-cw)//2
    truth=a[y0:y0+ch,x0:x0+cw]
    baseline=observed[y0:y0+ch,x0:x0+cw]
    assert np.mean(abs(corrected-truth))<np.mean(abs(baseline-truth))*.45


def radial_scene(a, k):
    """Independent inverse of x_d=x_u*(1+k*r^2), then sample the ideal scene."""
    h,w=a.shape[:2];r=np.hypot(w-1,h-1)/2
    yy,xx=np.indices((h,w));xd=(xx-(w-1)/2)/r;yd=(yy-(h-1)/2)/r
    rd=np.hypot(xd,yd)
    lo=np.zeros_like(rd);hi=np.full_like(rd,1.2)
    # Bisection avoids sharing the production Newton inversion.
    for _ in range(45):
        mid=(lo+hi)/2
        left=mid*(1+k*mid**2)<rd
        lo=np.where(left,mid,lo);hi=np.where(left,hi,mid)
    ru=(lo+hi)/2
    xu=xd*ru/np.maximum(rd,1e-8);yu=yd*ru/np.maximum(rd,1e-8)
    return np.stack([map_coordinates(a[...,ch],[yu*r+(h-1)/2,xu*r+(w-1)/2],order=1,mode='constant',cval=.76) for ch in range(3)],axis=-1)


@pytest.mark.parametrize('k',[-.18,-.08,.08,.20])
def test_auto_lens_recovers_barrel_and_pincushion(k):
    from geometry import estimate_lens
    result=estimate_lens(radial_scene(grid(),k))
    assert result['distortion'] is not None, result
    assert abs(result['distortion']-k*300)<3, result
    assert result['lens_lines']>=3


@pytest.mark.parametrize('k',[-.12,.15])
def test_one_click_joint_geometry(k):
    from geometry import automatic_geometry
    a=radial_scene(distort(grid(),3,25,-12),k)
    result=automatic_geometry(a)
    assert abs(result['distortion']-k*300)<4, result
    assert abs(result['angle']-3)<.5, result
    assert abs(result['vertical']-25)<3, result
    assert abs(result['horizontal']+12)<3, result


def test_auto_lens_rejects_noise_straight_lines_and_single_curve():
    from geometry import estimate_lens
    for a in [grid(),np.ones((300,400,3)),np.random.default_rng(5).random((300,400,3))]:
        assert estimate_lens(a)['distortion'] is None
    im=Image.new('RGB',(800,600),'white');d=ImageDraw.Draw(im)
    d.arc((50,20,700,650),20,340,fill='black',width=3)
    assert estimate_lens(np.asarray(im,dtype=float)/255)['distortion'] is None


def test_vote_level_matches_a_tilted_horizon():
    from PIL import Image, ImageDraw
    from geometry import level_by_votes

    for tilt in (3, -7.5):
        im = Image.new("RGB", (3600, 2400), (90, 110, 140))
        t = np.tan(np.radians(tilt)) * 1800
        ImageDraw.Draw(im).polygon(
            [(0, 1200 + t), (3600, 1200 - t), (3600, 2400), (0, 2400)], (60, 80, 40))
        a = np.asarray(im.resize((900, 600), Image.LANCZOS), np.float32) / 255
        assert abs(level_by_votes(a) - tilt) <= 0.2
    assert level_by_votes(np.random.default_rng(0).random((300, 400, 3))) is None
