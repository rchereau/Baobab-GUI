function events = detect_events(dff, fs, k, refractory_s)
%DETECT_EVENTS  Upward crossings of median + k*MAD, one cell array entry per cell.
if nargin < 3, k = 4; end
if nargin < 4, refractory_s = 0.5; end
med = median(dff, 1);
mad = median(abs(dff - med), 1) * 1.4826;
above = dff > med + k * mad;
refractory = round(refractory_s * fs);
events = cell(1, size(dff, 2));
for c = 1:size(dff, 2)
    onsets = find(above(2:end, c) & ~above(1:end-1, c)) + 1;
    kept = [];
    last = -refractory;
    for i = onsets'
        if i - last >= refractory
            kept(end + 1) = i; %#ok<AGROW>
            last = i;
        end
    end
    events{c} = kept;
end
end
