import { useId, type CSSProperties } from 'react';

/** Fixed illustrative geometry and timed loops; never receives job progress or coordinates. */
function PoseIllustration({ animate }: { animate: boolean }) {
  const clipId = useId();
  const route = 'M120 155 H630 Q650 155 650 135 V75 Q650 55 630 55 H120 Q100 55 100 75 V135 Q100 155 120 155 Z';
  return <svg className="processing-illustration processing-scanner" data-illustration="pose" viewBox="0 0 760 220" preserveAspectRatio="none" aria-hidden="true">
    <defs><clipPath id={clipId}><rect x="36" y="18" width="688" height="184" rx="12" /></clipPath></defs>
    <rect className="processing-scanner__floor" x="36" y="18" width="688" height="184" rx="12" />
    <g className="processing-scanner__grid" fill="none" stroke="currentColor">
      {[80,140,200,260,320,380,440,500,560,620,680].map(x => <path key={x} d={`M${x} 20V200`} />)}
      {[48,88,128,168].map(y => <path key={y} d={`M38 ${y}H722`} />)}
    </g>
    <g fill="none" stroke="#a8b7c7" strokeWidth="2">
      <rect x="36" y="18" width="688" height="184" rx="12" />
      <path d="M185 18V82 M380 140V202 M575 18V82" />
    </g>
    <g fill="#e0e8f1" stroke="#acbdd0" strokeWidth="1.5">
      <rect x="228" y="87" width="96" height="36" rx="3" />
      <rect x="454" y="87" width="84" height="36" rx="3" />
    </g>
    <g className="processing-scanner__points" fill="currentColor">
      {[[65,36],[142,31],[204,185],[265,188],[332,34],[403,33],[426,185],[477,187],[607,34],[694,165],[67,174]].map(([x,y],i) => <circle key={i} cx={x} cy={y} r="2" />)}
    </g>
    <path className="processing-scanner__route" d={route} fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="4 7" />
    <path className="processing-scanner__trail" d={route} pathLength="100" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    <g clipPath={`url(#${clipId})`}>
      <g className="processing-scanner__vehicle" style={animate ? { offsetPath: `path('${route}')` } : undefined} transform={animate ? undefined : 'translate(430 155)'}>
        <g className="processing-scanner__scan">
          <path d="M0 0 94 -48 A106 106 0 0 1 94 48Z" fill="currentColor" fillOpacity=".07" />
          <path d="M0 0 94 -48 M0 0H106 M0 0 94 48 M54 -28 A61 61 0 0 1 54 28 M80 -41 A90 90 0 0 1 80 41" fill="none" stroke="currentColor" strokeOpacity=".22" />
          <g fill="currentColor" opacity=".5"><circle cx="94" cy="-48" r="2" /><circle cx="106" cy="0" r="2.5" /><circle cx="94" cy="48" r="2" /></g>
        </g>
        <g className="processing-scanner__car">
          <rect x="-16" y="-14" width="32" height="28" rx="7" fill="currentColor" fillOpacity=".1" />
          <g fill="#454f5b"><rect x="-11" y="-14" width="7" height="5" rx="1" /><rect x="-11" y="9" width="7" height="5" rx="1" /><rect x="5" y="-14" width="7" height="5" rx="1" /><rect x="5" y="9" width="7" height="5" rx="1" /></g>
          <rect x="-14" y="-10" width="28" height="20" rx="4" fill="currentColor" />
          <rect x="-8" y="-6" width="14" height="12" rx="2" fill="#fff" />
          <rect x="10" y="-4" width="7" height="8" rx="2" fill="#00b8d9" />
          <circle cx="-1" cy="0" r="3" fill="currentColor" />
        </g>
      </g>
    </g>
  </svg>;
}

// An open isometric room, independent of the top-down Pose route.
function SurfaceIllustration() {
  const floorPoint = (u: number, v: number) => `${380 + (v - u) * 235},${82 + (u + v) * 58}`;
  const wallPoints = Array.from({ length: 28 }, (_, i) => {
    const t = (i % 7) / 6;
    const right = i >= 14;
    return [380 + (right ? 235 : -235) * t, 16 + t * 58 + (Math.floor(i / 7) % 2) * 66];
  });
  return <svg className="processing-illustration processing-surface" data-illustration="surface" viewBox="0 0 760 220" preserveAspectRatio="none" aria-hidden="true">
    <ellipse cx="380" cy="191" rx="259" ry="20" fill="currentColor" opacity=".04" />
    <g fill="currentColor" fillOpacity=".025" stroke="currentColor" strokeOpacity=".2" strokeWidth="1.4">
      <path d="M145 140V74L380 16 615 74V140L380 198Z M145 140 380 82 615 140 M380 16V82" />
    </g>
    <g className="processing-surface__tiles" stroke="currentColor" strokeWidth="1" strokeOpacity=".3">
      {Array.from({length:16},(_,i) => {
        const u = Math.floor(i / 4) / 4, v = (i % 4) / 4;
        return <polygon className="processing-surface__panel" key={i} style={{animationDelay:`${i * .07}s`}} points={`${floorPoint(u,v)} ${floorPoint(u+.25,v)} ${floorPoint(u+.25,v+.25)} ${floorPoint(u,v+.25)}`} fill="currentColor" fillOpacity={i % 2 ? '.14' : '.2'} />;
      })}
      {[0,1,2,3].map(i => <g key={i} className="processing-surface__panel" style={{animationDelay:`${.7 + i * .2}s`}}>
        <path d={`M${380-i*58.75} ${82+i*14.5}v-66l-58.75 14.5v66Z`} fill="#c9a5ef" />
        <path d={`M${380+i*58.75} ${82+i*14.5}v-66l58.75 14.5v66Z`} fill="#e0cef5" />
      </g>)}
    </g>
    <g fill="currentColor">
      {wallPoints.map(([x,y],i) => <circle className="processing-surface__point" key={i} cx={x} cy={y} r={i % 3 ? 2.2 : 3}
        style={{'--scatter-x':`${(i % 2 ? 1 : -1) * (28 + i % 5 * 12)}px`,'--scatter-y':`${(i % 3 - 1) * 12}px`,animationDelay:`${i * .035}s`} as CSSProperties} />)}
    </g>
  </svg>;
}

function DistanceIllustration() {
  return <svg className="processing-illustration processing-distance" data-illustration="distance" viewBox="0 0 760 220" preserveAspectRatio="none" aria-hidden="true">
    <rect x="36" y="18" width="688" height="184" rx="12" fill="#f0f7f8" stroke="#b6cbd0" strokeWidth="1.5" />
    <g stroke="currentColor" fill="none">
      {[1,2,3,4].map(i => <rect key={i} className="processing-distance__layer" style={{animationDelay:`${i * .9}s`}} x={290-i*17} y={87-i*15} width={116+i*34} height={46+i*30} rx={4+i*13} fill="currentColor" fillOpacity=".025" strokeWidth="1.5" />)}
      {[0,1,2].map(i => <path key={i} className="processing-distance__layer" style={{animationDelay:`${i * .9}s`}} d={`M${587-i*18} 38V108Q${587-i*18} ${151+i*15} ${638-i*4} ${151+i*15}H696`} strokeWidth="1.5" />)}
    </g>
    <g fill="#dae5e9" stroke="#9cb4bc" strokeWidth="1.5">
      <rect x="290" y="87" width="116" height="46" rx="4" />
      <path d="M607 38V108Q607 132 638 132H696V140H638Q599 140 599 108V38Z" />
    </g>
    <g stroke="currentColor" strokeWidth="1.5" fill="none">
      <path className="processing-distance__measure" d="M170 110H290 M348 87V35 M406 110H513" />
      <path d="M290 103V117 M341 87H355 M406 103V117" opacity=".65" />
      <g fill="#fff"><circle cx="170" cy="110" r="4" /><circle cx="348" cy="35" r="4" /><circle cx="513" cy="110" r="4" /></g>
    </g>
  </svg>;
}

export function ProcessingIllustration({ stage, animate }: { stage: string; animate: boolean }) {
  if (stage === 'surface') return <SurfaceIllustration />;
  if (stage === 'distance') return <DistanceIllustration />;
  return <PoseIllustration animate={animate} />;
}
