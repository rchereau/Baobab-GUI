function dff = delta_f_over_f(traces, pct)
%DELTA_F_OVER_F  dF/F per cell (columns), with F0 = a low percentile of each trace.
%   Computed by sorting, so no Statistics Toolbox is needed.
if nargin < 2, pct = 10; end
sorted = sort(traces, 1);
idx = max(1, round(pct / 100 * size(traces, 1)));
f0 = sorted(idx, :);
dff = (traces - f0) ./ f0;
end
