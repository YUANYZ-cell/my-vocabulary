// Adapted from the user-supplied Aurora GLSL. Local WebGL2, no extra dependencies.
const VERT = `#version 300 es
in vec2 position;
void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

const FRAG = `#version 300 es
precision highp float;

uniform float uTime;
uniform vec3 uColorStops[3];
uniform vec2 uResolution;

out vec4 fragColor;

vec3 permute(vec3 x) {
  return mod(((x * 34.0) + 1.0) * x, 289.0);
}

float snoise(vec2 v){
  const vec4 C = vec4(
      0.211324865405187, 0.366025403784439,
      -0.577350269189626, 0.024390243902439
  );
  vec2 i  = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod(i, 289.0);

  vec3 p = permute(
      permute(i.y + vec3(0.0, i1.y, 1.0))
    + i.x + vec3(0.0, i1.x, 1.0)
  );

  vec3 m = max(
      0.5 - vec3(
          dot(x0, x0),
          dot(x12.xy, x12.xy),
          dot(x12.zw, x12.zw)
      ), 
      0.0
  );
  m = m * m;
  m = m * m;

  vec3 x = 2.0 * fract(p * C.www) - 1.0;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);

  vec3 g;
  g.x  = a0.x  * x0.x  + h.x  * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);
}

struct ColorStop {
  vec3 color;
  float position;
};

#define COLOR_RAMP(colors, factor, finalColor) {              \
  int index = 0;                                            \
  for (int i = 0; i < 2; i++) {                               \
     ColorStop currentColor = colors[i];                    \
     bool isInBetween = currentColor.position <= factor;    \
     index = int(mix(float(index), float(i), float(isInBetween))); \
  }                                                         \
  ColorStop currentColor = colors[index];                   \
  ColorStop nextColor = colors[index + 1];                  \
  float range = nextColor.position - currentColor.position; \
  float lerpFactor = (factor - currentColor.position) / range; \
  finalColor = mix(currentColor.color, nextColor.color, lerpFactor); \
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution;
  
  ColorStop colors[3];
  colors[0] = ColorStop(uColorStops[0], 0.0);
  colors[1] = ColorStop(uColorStops[1], 0.5);
  colors[2] = ColorStop(uColorStops[2], 1.0);
  
  vec3 rampColor;
  COLOR_RAMP(colors, uv.x, rampColor);
  
  // Spatial noise defines a stable silhouette; time only adds bounded breathing.
  // The bands never travel across the text or swap colors.
  float noise = snoise(vec2(uv.x * 1.8, 2.4));
  float breath = sin(uTime * 0.22);
  float upperCenter = 0.94 - uv.x * 0.15
    + sin(uv.x * 4.5 + 0.3) * 0.075 + noise * 0.025 + breath * 0.006;
  float upperDistance = uv.y - upperCenter;
  float upperWidth = 0.085 + 0.012 * sin(uv.x * 3.1);
  float upperHalo = exp(-pow(upperDistance / (upperWidth * 2.6), 2.0));
  float upperVeil = 1.0 - smoothstep(upperWidth * 0.55, upperWidth * 1.7, abs(upperDistance));
  float upperLight = exp(-pow((upperDistance + upperWidth * 0.3) / (upperWidth * 0.6), 2.0));
  float lowerCenter = 0.19 + sin(uv.x * 3.7 + 0.7) * 0.13
    + snoise(vec2(uv.x * 1.7 + 7.0, 1.8)) * 0.02 - breath * 0.004;
  float lowerDistance = uv.y - lowerCenter;
  float lowerHalo = exp(-pow(lowerDistance / 0.24, 2.0));
  float lowerVeil = 1.0 - smoothstep(0.075, 0.16, abs(lowerDistance));
  vec3 lowerColor;
  COLOR_RAMP(colors, 1.0 - uv.x, lowerColor);
  vec3 paper = vec3(0.981, 0.990, 0.964);
  vec3 col = mix(paper, rampColor, upperHalo * 0.13 + upperVeil * (0.29 + breath * 0.018));
  col = mix(col, vec3(1.0), upperLight * 0.10);
  col = mix(col, lowerColor, lowerHalo * 0.08 + lowerVeil * (0.23 - breath * 0.012));
  float grain = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453) - 0.5;
  fragColor = vec4(col + grain * 0.002, 1.0);
}
`;

// Native WebGL2 lifecycle for the supplied Aurora noise field and visible veils.
export function mountAuroraBackground(container) {
  if (!container) return;
  const canvas = document.createElement('canvas');
  canvas.className = 'aurora-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  const gl = canvas.getContext('webgl2', { alpha: false, antialias: false, depth: false, powerPreference: 'low-power' });
  if (!gl) { container.dataset.aurora = 'fallback'; return; }
  let program, buffer;
  const shaders = [];
  try {
    for (const [type, source] of [[gl.VERTEX_SHADER,VERT],[gl.FRAGMENT_SHADER,FRAG]]) {
      const shader = gl.createShader(type);
      shaders.push(shader);
      gl.shaderSource(shader,source); gl.compileShader(shader);
      if (!gl.getShaderParameter(shader,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
    }
    program = gl.createProgram();
    shaders.forEach(shader=>gl.attachShader(program,shader));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    buffer=gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER,buffer);
    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
    const position=gl.getAttribLocation(program,'position');
    gl.enableVertexAttribArray(position); gl.vertexAttribPointer(position,2,gl.FLOAT,false,0,0);
    gl.uniform3fv(gl.getUniformLocation(program,'uColorStops[0]'),new Float32Array([
      0.64,0.79,0.48, // soft leaf green
      0.65,0.82,0.72, // muted jade
      0.85,0.86,0.60  // warm yellow green
    ]));
  } catch (error) {
    container.dataset.aurora='fallback';
    shaders.forEach(shader=>gl.deleteShader(shader));
    if(program)gl.deleteProgram(program);
    if(buffer)gl.deleteBuffer(buffer);
    console.warn('Aurora background unavailable:',error.message);
    return;
  }
  container.append(canvas);
  container.dataset.aurora='ready';
  const time=gl.getUniformLocation(program,'uTime');
  const resolution=gl.getUniformLocation(program,'uResolution');
  const reduce=matchMedia('(prefers-reduced-motion: reduce)');
  let frame=0,last=0,clock=14,lost=false;
  const draw=()=>{ gl.uniform1f(time,clock); gl.drawArrays(gl.TRIANGLES,0,3); };
  const resize=()=>{
    const rect=container.getBoundingClientRect();
    const scale=Math.min(1,1440/Math.max(1,rect.width));
    canvas.width=Math.max(1,Math.round(rect.width*scale));
    canvas.height=Math.max(1,Math.round(rect.height*scale));
    gl.viewport(0,0,canvas.width,canvas.height);
    gl.uniform2f(resolution,canvas.width,canvas.height);
    if(!lost)draw();
  };
  const loop=now=>{
    if(now-last>=1000/30){clock+=Math.min((now-last)/1000,0.1)*1.0;last=now;draw();}
    frame=requestAnimationFrame(loop);
  };
  const sync=()=>{
    cancelAnimationFrame(frame);frame=0;
    const paused=document.hidden||reduce.matches||lost;
    container.dataset.auroraMotion=paused?'paused':'running';
    if(!paused){last=performance.now();frame=requestAnimationFrame(loop);}
  };
  const observer=new ResizeObserver(resize); observer.observe(container);
  document.addEventListener('visibilitychange',sync);
  reduce.addEventListener('change',sync);
  canvas.addEventListener('webglcontextlost',event=>{
    event.preventDefault();lost=true;canvas.style.visibility='hidden';
    container.dataset.aurora='fallback';sync();
  });
  window.addEventListener('pagehide',()=>{
    cancelAnimationFrame(frame);observer.disconnect();
    document.removeEventListener('visibilitychange',sync);
    reduce.removeEventListener('change',sync);
    shaders.forEach(shader=>gl.deleteShader(shader));
    gl.deleteBuffer(buffer);gl.deleteProgram(program);
  },{once:true});
  resize();sync();
}
