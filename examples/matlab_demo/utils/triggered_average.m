function [axis_s, avg] = triggered_average(dff, t, onsets, pre_s, post_s)
%TRIGGERED_AVERAGE  Stimulus-triggered average dF/F: time axis and [time x cell] mean.
if nargin < 4, pre_s = 1; end
if nargin < 5, post_s = 3; end
fs = 1 / median(diff(t));
pre = round(pre_s * fs);
post = round(post_s * fs);
snippets = [];
for on = onsets(:)'
    [~, i] = min(abs(t - on));
    if i - pre >= 1 && i + post - 1 <= numel(t)
        snippets = cat(3, snippets, dff(i - pre:i + post - 1, :));
    end
end
axis_s = (-pre:post - 1)' / fs;
avg = mean(snippets, 3);
end
